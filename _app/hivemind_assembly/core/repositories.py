"""Domain-independent, durable provisioning of a project's repository (private unless the owner chooses public)."""

import json
import re
import threading
import time

from .common import Blocked, Conflict, ContractError, uid


def repository_args(args):
    if not isinstance(args, dict) or set(args) - {
        "name",
        "owner",
        "description",
        "visibility",
    }:
        raise ContractError(
            "Repository arguments are name, optional owner, description and visibility (private or public)."
        )
    visibility = args.get("visibility", "private")
    if visibility not in ("private", "public"):
        raise ContractError("Repository visibility must be private or public.")
    name, owner, description = (
        args.get("name"),
        args.get("owner", ""),
        args.get("description", ""),
    )
    if (
        not isinstance(name, str)
        or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", name)
        or name in (".", "..")
    ):
        raise ContractError(
            "Repository name must contain 1–100 letters, numbers, dots, underscores or hyphens."
        )
    if (
        not isinstance(owner, str)
        or owner
        and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", owner)
    ):
        raise ContractError("Invalid GitHub account or organization name.")
    if (
        not isinstance(description, str)
        or len(description) > 200
        or any(ord(x) < 32 for x in description)
    ):
        raise ContractError(
            "Repository description must be a single line of at most 200 characters."
        )
    return {
        "name": name,
        "owner": owner,
        "description": description,
        "visibility": visibility,
    }


class Repositories:
    """One primary repository per project, shared by all tasks and domains.

    A temporary description nonce distinguishes a lost creation response from a
    pre-existing repository. Once its ID is durable, remove the nonce and retain
    the requested description. No source files or commits are created.

    Visibility is recorded with each request: private unless the owner chose
    public. A repository whose visibility later differs from the record is
    refused, so a private project is never published to a repository that has
    since been made public.
    """

    def __init__(self, store, client, config):
        self.store, self.client, self.config = store, client, config
        self.lock = threading.RLock()

    def link(self, project, operation_id, args):
        """Owner-requested binding to an existing repository; no creation.

        The repository's current visibility (private or public) is recorded and
        must stay the same for later publications."""
        args = repository_args(args)
        with self.lock:
            user = self._identity()
            owner = args["owner"] or user["login"]
            repo = self.client.lookup(owner, args["name"])
            row = {"owner": owner, "name": args["name"], "repository_id": ""}
            visibility = (
                "public"
                if isinstance(repo, dict) and repo.get("private") is False
                else "private"
            )
            self._validate(row, repo, visibility=visibility)
            existing = self.status(project)
            if existing.get("state"):
                if (
                    existing.get("repository_id") == str(repo["id"])
                    and existing["state"] == "verified"
                ):
                    self._identity(self._row(project))
                    self._bind(self._row(project), operation_id)
                    return {"status": "saved", **existing}
                raise Conflict(
                    "Project already has a repository binding; it cannot be replaced automatically"
                )
            branch = repo.get("default_branch", "main")
            head = self.client.head(owner, args["name"], branch)
            with self.store.tx() as db:
                db.execute(
                    "INSERT INTO project_repositories(project_id,operation_id,owner,name,description,account_id,marker,state,repository_id,url,error,created,updated) VALUES(?,?,?,?,?,?,?,'verified',?,?,?, ?,?)",
                    (
                        project,
                        operation_id,
                        owner,
                        args["name"],
                        repo.get("description") or "",
                        user["id"],
                        "",
                        str(repo["id"]),
                        f"https://github.com/{owner}/{args['name']}",
                        "",
                        time.time(),
                        time.time(),
                    ),
                )
                self.store.put(
                    "publication_head:" + project,
                    uid("state"),
                    {"branch": branch, "sha": head},
                    db,
                )
                self.store.put(
                    "repository_operation",
                    operation_id,
                    {"project_id": project, "marker": ""},
                    db,
                )
                self.store.put(
                    "repository_visibility",
                    operation_id,
                    {"visibility": visibility},
                    db,
                )
            return {"status": "saved", **self.status(project)}

    def status(self, project):
        rows = self.store.rows(
            "SELECT * FROM project_repositories WHERE project_id=?", (project,)
        )
        if not rows:
            return {"status": "unlinked"}
        row = rows[0]
        return {
            **{
                k: row[k]
                for k in (
                    "project_id",
                    "owner",
                    "name",
                    "state",
                    "repository_id",
                    "url",
                    "error",
                )
            },
            "visibility": self._visibility(row),
        }

    def _visibility(self, row):
        rows = self.store.rows(
            "SELECT payload FROM records WHERE kind='repository_visibility' AND id=?",
            (row["operation_id"],),
        )
        return json.loads(rows[0]["payload"])["visibility"] if rows else "private"

    def uncertain(self, project, operation_id):
        return bool(
            self.store.rows(
                "SELECT 1 FROM records WHERE kind='repository_operation' AND id=?",
                (operation_id,),
            )
        ) and self.status(project).get("state") in ("pending", "identified", "verified")

    def _bind(self, row, operation_id):
        self.store.put(
            "repository_operation",
            operation_id,
            {"project_id": row["project_id"], "marker": row["marker"]},
        )

    def _update(self, project, **values):
        with self.store.tx() as db:
            db.execute(
                "UPDATE project_repositories SET "
                + ",".join(k + "=?" for k in values)
                + ",updated=? WHERE project_id=?",
                (*values.values(), time.time(), project),
            )

    def _row(self, project):
        return self.store.one(
            "SELECT * FROM project_repositories WHERE project_id=?", (project,)
        )

    def _identity(self, row=None):
        user = self.client.identity()
        if row and user["id"] != row["account_id"]:
            raise Blocked(
                "Repository belongs to a different GitHub authorization. Reconnect the original account."
            )
        return user

    def create(self, project, operation_id, args, cancel=None):
        args = repository_args(args)
        if not self.config.get("github", {}).get("allow_repository_creation", False):
            raise Blocked("Enable repository creation in GitHub settings first.")
        with self.lock:
            user = self._identity()
            owner = args["owner"] or user["login"]
            allowed = {
                user["login"].lower(),
                *(
                    x.lower()
                    for x in self.config.get("github", {}).get(
                        "allowed_organizations", []
                    )
                ),
            }
            if owner.lower() not in allowed:
                raise Blocked(
                    "Repository owner is not the authorized account or an allowed organization."
                )
            self.store.project(project)
            rows = self.store.rows(
                "SELECT * FROM project_repositories WHERE project_id=?", (project,)
            )
            if rows:
                row = rows[0]
                if (
                    row["owner"].lower(),
                    row["name"].lower(),
                    row["description"],
                    self._visibility(row),
                ) != (
                    owner.lower(),
                    args["name"].lower(),
                    args["description"],
                    args["visibility"],
                ):
                    if (
                        row["state"] in ("prepared", "rejected", "conflict")
                        and not row["repository_id"]
                    ):
                        with self.store.tx() as db:
                            self.store.put(
                                "repository_request_retired", uid("retired"), row, db
                            )
                            db.execute(
                                "DELETE FROM project_repositories WHERE project_id=?",
                                (project,),
                            )
                        return self.create(project, operation_id, args, cancel)
                    raise Conflict(
                        "This project already has a different repository request. Reuse its recorded repository."
                    )
                self._identity(row)
                if row["state"] in ("pending", "identified", "verified"):
                    self._bind(row, operation_id)
                    return self._verify(row)
                if row["state"] == "conflict":
                    raise Conflict(row["error"])
            else:
                with self.store.tx() as db:
                    other = db.execute(
                        "SELECT project_id FROM project_repositories WHERE owner=? COLLATE NOCASE AND name=? COLLATE NOCASE",
                        (owner, args["name"]),
                    ).fetchone()
                    if other:
                        raise Conflict(
                            "This repository name is already reserved by another project."
                        )
                    db.execute(
                        "INSERT INTO project_repositories(project_id,operation_id,owner,name,description,account_id,marker,state,created,updated) VALUES(?,?,?,?,?,?,?,'prepared',?,?)",
                        (
                            project,
                            operation_id,
                            owner,
                            args["name"],
                            args["description"],
                            user["id"],
                            "[ha-provision:" + uid("repo") + "]",
                            time.time(),
                            time.time(),
                        ),
                    )
                    self.store.put(
                        "repository_visibility",
                        operation_id,
                        {"visibility": args["visibility"]},
                        db,
                    )
                row = self._row(project)
            # A pre-existing name is never silently adopted or overwritten.
            if self.client.lookup(row["owner"], row["name"]) is not None:
                message = "Repository already exists; no changes made. Choose a different name before provisioning."
                self._update(project, state="conflict", error=message)
                raise Conflict(message)
            if cancel is not None and cancel.is_set():
                raise Blocked("Task cancelled before repository creation.")
            self._bind(row, operation_id)
            self._update(project, state="pending", error="")
            self.store.event(
                project,
                "repository_creation_requested",
                {
                    "owner": owner,
                    "name": args["name"],
                    "visibility": self._visibility(row),
                },
            )
            try:
                created = self.client.create(
                    row["owner"],
                    row["name"],
                    self._marked(row),
                    organization=owner.lower() != user["login"].lower(),
                    private=self._visibility(row) == "private",
                )
            except Exception as error:
                # These responses definitively reject creation. Transport errors,
                # 5xx and malformed responses keep pending and never repeat POST.
                if getattr(error, "status", None) in (400, 401, 403, 404, 422, 429):
                    self._update(project, state="rejected", error=str(error))
                    raise
                self._update(
                    project,
                    error="Creation response uncertain; reconcile before retrying.",
                )
                raise Blocked(
                    "Repository creation response uncertain. Reconcile the saved request; do not choose a new name."
                ) from None
            self._validate(row, created, require_marker=True)
            self._update(project, state="identified", repository_id=str(created["id"]))
            return self._verify(self._row(project))

    @staticmethod
    def _marked(row):
        return (row["description"] + " " + row["marker"]).strip()

    def _validate(self, row, repo, require_marker=False, visibility=None):
        if visibility is None:
            visibility = self._visibility(row)
        if (
            not isinstance(repo, dict)
            or str(repo.get("full_name", "")).lower()
            != (row["owner"] + "/" + row["name"]).lower()
            or repo.get("private") is not (visibility == "private")
            or repo.get("archived") is True
            or repo.get("permissions", {}).get("push") is not True
            or not repo.get("id")
        ):
            raise Conflict(
                f"Repository identity, {visibility} visibility or write access could not be verified."
            )
        if row["repository_id"] and str(repo["id"]) != row["repository_id"]:
            raise Conflict(
                "Repository identity changed. Refusing to adopt a replacement."
            )
        if require_marker and repo.get("description") != self._marked(row):
            raise Conflict(
                "Repository does not carry this creation request's identity. No changes made."
            )

    def _verify(self, row):
        observed = self.client.lookup(row["owner"], row["name"])
        if observed is None:
            raise Blocked(
                "Repository is not visible. Absence may mean lost access; creation will not be replayed."
            )
        self._validate(row, observed, require_marker=not row["repository_id"])
        if not row["repository_id"]:
            self._update(
                row["project_id"], state="identified", repository_id=str(observed["id"])
            )
            row = self._row(row["project_id"])
        if row["marker"] and observed.get("description") == self._marked(row):
            self.client.describe(row["owner"], row["name"], row["description"])
            observed = self.client.lookup(row["owner"], row["name"])
            self._validate(row, observed)
            if (observed.get("description") or "") != row["description"]:
                raise Blocked(
                    "Repository created; description cleanup is still unverified."
                )
        # Later human description changes are preserved once the ID is known.
        url = f"https://github.com/{row['owner']}/{row['name']}"
        if row["state"] != "verified":
            self._update(row["project_id"], state="verified", url=url, error="")
            self.store.event(
                row["project_id"],
                "repository_verified",
                {
                    "repository_id": str(observed["id"]),
                    "url": url,
                    "private": self._visibility(row) == "private",
                },
            )
        return {
            "status": "saved",
            "repository_id": str(observed["id"]),
            "url": url,
            "owner": row["owner"],
            "name": row["name"],
            "private": self._visibility(row) == "private",
            "visibility": self._visibility(row),
            "initialized": False,
            "project_id": row["project_id"],
        }

    def reconcile(self, project, operation_id=None):
        with self.lock:
            rows = self.store.rows(
                "SELECT * FROM project_repositories WHERE project_id=?", (project,)
            )
            if not rows or rows[0]["state"] in ("prepared", "rejected", "conflict"):
                return {"status": "not_applied"}
            row = rows[0]
            if operation_id:
                bindings = self.store.rows(
                    "SELECT payload FROM records WHERE kind='repository_operation' AND id=?",
                    (operation_id,),
                )
                if not bindings:
                    return {"status": "not_applied"}
                binding = self.store.get("repository_operation", operation_id)
                if binding != {"project_id": project, "marker": row["marker"]}:
                    raise Conflict(
                        "Repository request identity changed before reconciliation."
                    )
            self._identity(row)
            return self._verify(row)
