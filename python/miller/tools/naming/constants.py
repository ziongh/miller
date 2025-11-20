"""
Constants for naming variant generation.
"""

MATCH_STRATEGIES = [
    "exact_match",  # UserService == UserService
    "case_insensitive",  # userservice == UserService
    "snake_pascal",  # user_service == UserService
    "camel_pascal",  # userService == UserService
    "prefix_strip",  # IUser == User
    "suffix_strip",  # UserDto == User
    "plural_singular",  # users == user
    "kebab_snake",  # user-service == user_service
    "screaming_variations",  # USER_SERVICE variations
    "interface_class",  # IUser == User
    "dto_model_strip",  # UserDto == User
    "namespace_qualified",  # app.user == user
    "partial_match",  # UserProfile contains User
    "word_overlap",  # UserProfileService overlaps UserService (2 of 3 words)
    "semantic_similarity",  # "auth" ~ "authentication" (embeddings)
]

MIN_SYMBOL_LENGTH = 1  # Minimum length for valid symbol name
MAX_SYMBOL_LENGTH = 255  # Maximum length (database limit)

PLURAL_EXCEPTIONS = {
    "person": "people",
    "child": "children",
    "tooth": "teeth",
    "foot": "feet",
    "mouse": "mice",
    "goose": "geese",
    "man": "men",
    "woman": "women",
}

SINGULAR_EXCEPTIONS = {v: k for k, v in PLURAL_EXCEPTIONS.items()}

# Common prefixes by language
LANGUAGE_PREFIXES = {
    "typescript": ["I", "T"],  # IUser, TUser
    "csharp": ["I"],  # IUserService
    "go": ["I"],  # IReader
    "rust": [],  # No interface prefix convention
    "python": [],  # No interface convention
}

LANGUAGE_SUFFIXES = {
    "typescript": ["Dto", "Model", "Entity", "Service", "Controller", "Repository"],
    "csharp": ["Dto", "Model", "Entity", "Service", "Controller", "Repository", "Request", "Response"],
    "java": ["Dto", "Model", "Entity", "Service", "Controller", "Repository", "Impl"],
    "python": ["_dto", "_model", "_entity", "_service", "_controller", "_repository"],
    "rust": [],  # Rust tends not to use suffix conventions
}

# Database-specific conventions
SQL_TABLE_CONVENTIONS = [
    "plural_snake_case",  # users, user_profiles
    "singular_snake_case",  # user, user_profile
]
