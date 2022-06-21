from copy import deepcopy
from pecan import expose, abort
from shaman.models import Repo, Project, Arch
from shaman import util
from sqlalchemy import desc, or_, and_


class SearchController(object):

    def __init__(self):
        self.filters = {
            'ref': Repo.ref,
            'sha1': Repo.sha1,
            'flavor': Repo.flavor,
            'status': Repo.status,
        }

    @expose('json')
    def index(self, **kw):
        """
        Supported query args:
        distros: distro/distro_version or distro/distro_codename
        sha1: actual sha1 or "latest"
        ref: limit by ref
        flavor: limit by flavor
        status: limit by status
        """
        query = self.apply_filters(kw)
        if not query:
            return []
        # order all the results by their modified time, descending (newest first)
        latest_modified_repos = query.order_by(desc(Repo.modified))
        distro_list = util.parse_distro_query(kw.get("distros"))
        if kw.get('sha1', '') == 'latest':
            seen_sha1s = []

            # go through all the sha1s in the repositories left from the
            # filtering, skipping the ones already queried for. We don't use
            # `set` here because it alters the ordering on `modified` from the
            # initial query
            for r in latest_modified_repos:
                if r.sha1 in seen_sha1s:
                    continue
                seen_sha1s.append(r.sha1)
                latest = []
                if not distro_list:
                    return latest_modified_repos.filter_by(sha1=r.sha1).all()

                for distro in distro_list:
                    version_filter = distro['distro_version']
                    latest_repo = latest_modified_repos.filter(
                        Repo.sha1 == r.sha1,
                        Repo.distro_version == version_filter
                    )
                    if distro["arch"]:
                        latest_repo = latest_repo.filter(Arch.name == distro["arch"])
                    latest_repo = latest_repo.order_by(desc(Repo.modified)).first()
                    if not latest_repo:
                        # a required repo that matches the sha1 and the distro
                        # version was not found, so break out of this inner
                        # loop, reset `latest` so that it doesn't return with
                        # the items found so that the outer loop can continue
                        # looking at the next sha1
                        latest = []
                        break
                    latest.append(latest_repo)
                # only return if the sha1 is found in all distros
                if latest:
                    return latest
            return []

        return latest_modified_repos.all()

    def apply_filters(self, filters):
        # TODO: allow operators
        filters = deepcopy(filters)
        try:
            project = Project.filter_by(name=filters.pop('project')).first()
            query = Repo.filter_by(project=project)
        except KeyError:
            query = Repo.query
        if filters.get("distros", None):
            # TODO: we'll need some sort of schema validation here
            distro_list = util.parse_distro_query(filters.pop("distros"))
            distro_filter_list = []
            has_arch_filter = False
            for distro in distro_list:
                # for deb-based distros we store codename in the db as version,
                # so try first with the codename, but fallback to
                # distro_version otherwise
                version_filter = distro['distro_version']
                if not version_filter:
                    abort(400, "Invalid version or codename for distro: %s" % distro["distro"])
                repo_filters = [Repo.distro == distro["distro"], Repo.distro_version == version_filter]
                if distro["arch"]:
                    repo_filters.append(Arch.name == distro["arch"])
                    has_arch_filter = True
                distro_filter_list.append(
                    and_(*repo_filters)
                )
            if has_arch_filter:
                query = query.join(Repo.archs).filter(or_(*distro_filter_list))
            else:
                query = query.filter(or_(*distro_filter_list))
        for k, v in filters.items():
            if k not in self.filters:
                # TODO: improve error reporting
                # 'invalid query params: %s' % k
                abort(400)
            if k in self.filters:
                query = self.filter_repo(k, v, query)
        return query

    def filter_repo(self, key, value, query=None):
        filter_obj = self.filters[key]

        if key == 'sha1' and value == 'latest':
            # we parse this elsewhere
            return query
        # query will exist if multiple filters are being applied, e.g. by name
        # and by distro but otherwise it will be None
        if query:
            return query.filter(filter_obj == value)
        return Repo.query.filter(filter_obj == value)
