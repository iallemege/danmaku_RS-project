from __future__ import annotations

import json
from typing import List, Optional

from danmaku_rs.config import accounts_path
from danmaku_rs.repo.secret import protect, unprotect
from danmaku_rs.types import Account


class AccountStore:
    def __init__(self):
        self.active_uid = ""
        self.accounts: List[Account] = []
        self.load()

    def load(self) -> None:
        path = accounts_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        self.active_uid = str(data.get("active") or "")
        self.accounts = [
            Account(
                uid=str(item.get("uid") or ""),
                uname=str(item.get("uname") or ""),
                sessdata=unprotect(str(item.get("sessdata") or "")),
                bili_jct=unprotect(str(item.get("bili_jct") or "")),
                buvid3=unprotect(str(item.get("buvid3") or "")),
                level=int(item.get("level") or 0),
                participate=bool(item.get("participate", True)),
            )
            for item in data.get("accounts") or []
        ]

    def save(self) -> None:
        payload = {
            "active": self.active_uid,
            "accounts": [
                {
                    "uid": acc.uid,
                    "uname": acc.uname,
                    "sessdata": protect(acc.sessdata),
                    "bili_jct": protect(acc.bili_jct),
                    "buvid3": protect(acc.buvid3),
                    "level": acc.level,
                    "participate": acc.participate,
                }
                for acc in self.accounts
            ],
        }
        accounts_path().write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def upsert(self, account: Account) -> None:
        for idx, existing in enumerate(self.accounts):
            if existing.uid == account.uid or existing.sessdata == account.sessdata:
                account.participate = existing.participate
                self.accounts[idx] = account
                self.active_uid = account.uid
                self.save()
                return
        self.accounts.append(account)
        self.active_uid = account.uid
        self.save()

    def remove(self, uid: str) -> None:
        self.accounts = [acc for acc in self.accounts if acc.uid != uid]
        if self.active_uid == uid:
            self.active_uid = self.accounts[0].uid if self.accounts else ""
        self.save()

    def active(self) -> Optional[Account]:
        for acc in self.accounts:
            if acc.uid == self.active_uid:
                return acc
        return self.accounts[0] if self.accounts else None

    def by_uids(self, uids) -> List[Account]:
        wanted = {str(uid) for uid in uids}
        return [acc for acc in self.accounts if acc.uid in wanted]

    def participating(self) -> List[Account]:
        chosen = [acc for acc in self.accounts if acc.participate]
        return chosen or ([self.active()] if self.active() else [])

    def set_participate(self, uid: str, flag: bool) -> None:
        for acc in self.accounts:
            if acc.uid == uid:
                acc.participate = flag
        self.save()
