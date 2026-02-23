class RequireAuthenticationMiddleware:
    def resolve(self, next, root, info, **args):
        field = info.field_name
        print(info.parent_type.name)

        is_root = info.parent_type.name in ("Query", "Mutation", "Subscription")

        public = [
            "loginUser",
            "registerUser",
            "session",
            "__schema",
            "__type"
        ]

        if is_root and field in public:
            return next(root, info, **args)

        if is_root:
            if not info.context.user.is_authenticated:
                raise Exception("Authentication required")

        return next(root, info, **args)
