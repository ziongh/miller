// Realistic Rust code
use std::collections::HashMap;

pub trait UserRepository {
    fn find_user(&self, id: u64) -> Option<User>;
    fn save_user(&mut self, user: User) -> Result<(), String>;
}

#[derive(Debug, Clone)]
pub struct User {
    pub id: u64,
    pub name: String,
    pub email: String,
}

pub struct InMemoryRepo {
    users: HashMap<u64, User>,
}

impl InMemoryRepo {
    pub fn new() -> Self {
        Self {
            users: HashMap::new(),
        }
    }
}

impl UserRepository for InMemoryRepo {
    fn find_user(&self, id: u64) -> Option<User> {
        self.users.get(&id).cloned()
    }

    fn save_user(&mut self, user: User) -> Result<(), String> {
        self.users.insert(user.id, user);
        Ok(())
    }
}

pub fn validate_email(email: &str) -> bool {
    email.contains('@')
}
