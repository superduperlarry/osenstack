"""Bootstrap a sandbox owner: verified, funded treasury, owner key printed once.

The spec deliberately has no signup endpoint — owner onboarding (KYC/KYB) is a
console flow. This is its sandbox stand-in.

Usage: uv run python scripts/seed_sandbox.py
"""

import asyncio
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


async def main() -> None:
    from enos import ids
    from enos.db import dispose_engine, get_sessionmaker
    from enos.models import Owner
    from enos.services import ledger
    from enos.services.credentials import issue_owner_key

    async with get_sessionmaker()() as session:
        owner = Owner(
            id=ids.new_id(ids.OWNER),
            type="business",
            legal_name="Sandbox Trading Pte. Ltd.",
            display_name="Sandbox Trading",
            verification_status="verified",
            country="SG",
            default_currency="USD",
        )
        session.add(owner)
        await session.flush()
        credential, secret = await issue_owner_key(session, owner, label="sandbox owner key")
        await ledger.fund(
            session,
            owner=owner,
            holder_type="owner",
            holder_id=owner.id,
            amount=Decimal("10000.00"),
            resource_type="funding",
            resource_id="sandbox_seed",
        )
        await session.commit()

    print("Sandbox owner created.")
    print(f"  owner_id:  {owner.id}")
    print("  treasury:  10000.00 USD")
    print(f"  owner key: {secret}")
    print("Store the key securely — it is not shown again.")
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
