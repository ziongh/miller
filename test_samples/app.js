// Realistic JavaScript/Node.js code
const express = require('express');

class UserService {
    constructor(database) {
        this.db = database;
        this.cache = new Map();
    }

    async findUser(userId) {
        if (this.cache.has(userId)) {
            return this.cache.get(userId);
        }

        const user = await this.db.users.findOne({ id: userId });
        this.cache.set(userId, user);
        return user;
    }

    validateEmail(email) {
        return email.includes('@');
    }
}

async function createApp() {
    const app = express();
    const service = new UserService(database);

    app.get('/users/:id', async (req, res) => {
        const user = await service.findUser(req.params.id);
        res.json(user);
    });

    return app;
}

module.exports = { UserService, createApp };
