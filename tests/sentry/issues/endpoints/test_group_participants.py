from collections.abc import Callable

from sentry.models.group import Group
from sentry.models.groupsubscription import GroupSubscription
from sentry.testutils.cases import APITestCase


class GroupParticipantsTest(APITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.login_as(self.user)

    def _get_path_functions(self) -> tuple[Callable[[Group], str], Callable[[Group], str]]:
        # The urls for group participants are supported both with an org slug and without.
        # We test both as long as we support both.
        # Because removing old urls takes time and consideration of the cost of breaking lingering references, a
        # decision to permanently remove either path schema is a TODO.
        return (
            lambda group: f"/api/0/issues/{group.id}/participants/",
            lambda group: f"/api/0/organizations/{self.organization.slug}/issues/{group.id}/participants/",
        )

    def test_simple(self) -> None:
        group = self.create_group()
        GroupSubscription.objects.create(
            user_id=self.user.id, group=group, project=group.project, is_active=True
        )

        for path_func in self._get_path_functions():
            path = path_func(group)

            response = self.client.get(path)
            assert len(response.data) == 1, response
            assert response.data[0]["id"] == str(self.user.id)
