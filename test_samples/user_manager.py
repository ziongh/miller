import os
from typing import List, Optional

class UserManager:
    """Manages user operations."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._cache = {}

    async def get_user(self, user_id: int) -> Optional[dict]:
        """Fetch user by ID."""
        if user_id in self._cache:
            return self._cache[user_id]
        return None

    @staticmethod
    def validate_email(email: str) -> bool:
        """Validate email format."""
        return '@' in email

def main():
    manager = UserManager('/data/users.db')
    print('Ready')

if __name__ == '__main__':
    main()
