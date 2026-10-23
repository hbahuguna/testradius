module.exports = {
  extends: ["@commitlint/config-conventional"],
  rules: {
    "scope-enum": [
      2,
      "always",
      [
        "cell",
        "cp",
        "web",
        "shared-types",
        "fixtures",
        "infra",
        "ci",
        "docs",
        "adr",
        "sprint",
        "instrumentation",
        "analysis",
        "graph",
      ],
    ],
    "subject-case": [2, "always", "lower-case"],
    "header-max-length": [2, "always", 100],
  },
};
