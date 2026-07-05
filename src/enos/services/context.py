"""The authenticated principal, resolved from a bearer token."""

from dataclasses import dataclass

from enos.models import Agent, Credential, Owner
from enos.services.errors import forbidden_scope, owner_scope_required


@dataclass
class Principal:
    owner: Owner
    credential: Credential
    agent: Agent | None = None  # None ⇒ owner key (ok_…)

    @property
    def is_owner(self) -> bool:
        return self.agent is None

    @property
    def scopes(self) -> list[str]:
        return list(self.credential.scopes or [])

    def require_owner(self) -> None:
        if not self.is_owner:
            raise owner_scope_required()

    def require_scope(self, scope: str) -> None:
        """Owner keys carry full account scope; agent credentials need the scope."""
        if self.is_owner:
            return
        if scope not in self.scopes:
            raise forbidden_scope(scope)
