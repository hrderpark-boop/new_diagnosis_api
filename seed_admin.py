"""초기 어드민 계정/고객사 시드 스크립트.

사용법:
    # 운영자(Super Admin) 생성
    python seed_admin.py --email ops@connectn.co.kr --password '강력한비밀번호' --role super_admin --name 운영자

    # 고객사 + 고객사 담당자(Client Admin) 생성
    python seed_admin.py --company-name '커넥트앤컴퍼니' --company-code CONNECTN \
        --email hr@client.com --password '강력한비밀번호' --role client_admin --name 'HR담당자'

비밀번호는 인자로만 받으며 코드/DB 어디에도 평문으로 남지 않는다(bcrypt 해시 저장).
이미 존재하는 이메일이면 아무것도 바꾸지 않고 종료한다.
"""

import argparse
import asyncio
import sys

from sqlalchemy.future import select

from diag_project.database import async_session
from diag_project.models.admin_user import AdminUser, UserRole
from diag_project.models.company import Company
from diag_project.services.auth import hash_password


async def seed(args) -> int:
    async with async_session() as db:
        company = None

        # 1) 고객사 확보 (코드가 주어진 경우: 있으면 재사용, 없으면 생성)
        if args.company_code:
            company = (
                await db.execute(select(Company).where(Company.code == args.company_code))
            ).scalars().first()
            if company:
                print(f"ℹ️  기존 고객사 사용: {company.name} ({company.code})")
            else:
                company = Company(
                    name=args.company_name or args.company_code,
                    code=args.company_code,
                )
                db.add(company)
                await db.commit()
                await db.refresh(company)
                print(f"✅ 고객사 생성: {company.name} ({company.code})")

        # 2) 권한 검증
        if args.role == UserRole.CLIENT_ADMIN.value and company is None:
            print("❌ client_admin 은 --company-code 가 필요합니다.")
            return 1

        # 3) 관리자 계정 생성
        email = args.email.strip().lower()
        exists = (
            await db.execute(select(AdminUser).where(AdminUser.email == email))
        ).scalars().first()
        if exists:
            print(f"⚠️  이미 존재하는 계정입니다: {email} (변경 없이 종료)")
            return 0

        admin = AdminUser(
            email=email,
            name=args.name,
            role=args.role,
            password_hash=hash_password(args.password),
            company_id=company.id if company else None,
        )
        db.add(admin)
        await db.commit()
        await db.refresh(admin)

        print(f"✅ 관리자 생성 완료: {admin.email} / role={admin.role}")
        if company:
            print(f"   소속 고객사: {company.name} ({company.code})")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="어드민 계정 시드")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--name", default=None)
    parser.add_argument(
        "--role",
        default=UserRole.CLIENT_ADMIN.value,
        choices=[UserRole.SUPER_ADMIN.value, UserRole.CLIENT_ADMIN.value],
    )
    parser.add_argument("--company-code", default=None)
    parser.add_argument("--company-name", default=None)
    args = parser.parse_args()

    if len(args.password) < 8:
        print("❌ 비밀번호는 8자 이상이어야 합니다.")
        return 1

    return asyncio.run(seed(args))


if __name__ == "__main__":
    sys.exit(main())
