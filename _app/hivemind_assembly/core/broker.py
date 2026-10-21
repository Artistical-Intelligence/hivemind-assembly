from __future__ import annotations
import json, threading
from hivemind_assembly.core.common import (
    scoped,
    atomic_write,
    file_hash,
    canonical,
    Blocked,
    ContractError,
    Conflict,
)
from hivemind_assembly.core.artifacts import Artifacts
from hivemind_assembly.core.jobs import Jobs

from .domain import Capability, ToolContext

CORE_CAPABILITIES = (
    Capability("list_files", recovery="discard"),
    Capability("mcp_call", True, "external"),
    Capability("cloud_submit", True, "external"),
    Capability("cloud_status", recovery="discard"),
    Capability("read_file", recovery="discard"),
    Capability("write_file", True, "reconcile"),
    Capability("checkpoint", recovery="discard"),
    Capability("read_artifact", recovery="discard"),
    Capability("verified_sources", recovery="discard"),
    Capability("run_workflow", recovery="discard"),
    Capability("test_programs", recovery="external"),
    Capability("propose_workflow", recovery="discard"),
)


class Broker:
    def __init__(
        self, controller, config, domain=None, repositories=None, hosted_tests=None
    ):
        self.controller = controller
        self.store = controller.store
        self.config = config
        self.artifacts = Artifacts(self.store)
        from .verified_sources import VerifiedSources

        self.verified_sources = VerifiedSources(self.store, self.artifacts)
        self.jobs = Jobs()
        self.cancel = {}
        self.domain = domain
        self.repositories = repositories
        self.hosted_tests = hosted_tests
        from .publication import Publications

        self.publications = Publications(repositories) if repositories else None
        repository_specs = (
            (
                Capability("create_repository", True, "reconcile"),
                Capability("link_repository", True, "reconcile"),
                Capability("publish_checkpoint", True, "reconcile"),
                Capability("repository_status", recovery="discard"),
            )
            if repositories
            else ()
        )
        specs = (
            *CORE_CAPABILITIES,
            *repository_specs,
            *(
                (Capability("hosted_test_status", recovery="discard"),)
                if hosted_tests
                else ()
            ),
            *(domain.capabilities if domain else ()),
        )
        self.capabilities = {spec.name: spec for spec in specs}
        if len(self.capabilities) != len(specs):
            raise ContractError("Domain capability collides with an existing operation")
        for spec in specs:
            if spec.recovery not in ("discard", "reconcile", "external"):
                raise ContractError("Unknown capability recovery policy")
            if spec.mutates_project and spec.recovery == "discard":
                raise ContractError(
                    "A project mutation cannot be discarded during recovery"
                )
        self.mutations = {spec.name for spec in specs if spec.mutates_project}

    def context(self, task, tool=None):
        return ToolContext(
            self.workspace(task),
            self.config,
            self.jobs,
            self.cancel.setdefault(task, threading.Event()),
            self.verified_sources.last_composition(task)
            if tool == "compare_project"
            else None,
        )

    def workspace(self, task):
        return (
            self.store.root
            / "projects"
            / self.store.task(task)["project_id"]
            / "workspace"
        )

    def execute(self, request):
        if request.get("knowledge_scope"):
            from hivemind_assembly.learning.scopes import KnowledgeScopes

            if (
                KnowledgeScopes(self.store).fingerprint(request["task_id"])
                != request["knowledge_scope"]
            ):
                raise Blocked(
                    "Tool request has a stale knowledge scope; rebrief required"
                )
        op, new = self.controller.begin(request, self.capabilities)
        if not new:
            if op["state"] in ("completed", "saved", "failed"):
                return json.loads(op["result"])
            raise Blocked("Operation delivery uncertain; reconcile before retry")
        task = request["task_id"]
        root = self.workspace(task)
        args = request["args"]
        tool = request["tool"]
        cancel = self.cancel.setdefault(task, threading.Event())
        effect_started = False
        try:
            self.controller.traces.append(
                task, request["id"], request["owner"], "tool_request", request
            )
            if cancel.is_set():
                raise Blocked("Task cancelled")
            if tool == "mcp_call":
                import asyncio

                connections = getattr(self, "mcp_connections", None)
                if not connections:
                    raise Blocked("No external MCP connections configured")
                connections.authorize(
                    args["server"], args["tool"], self.store.task(task)["project_id"]
                )
                effect_started = True
                result = asyncio.run(
                    connections.external(
                        args["server"],
                        args["tool"],
                        args.get("arguments", {}),
                        self.store.task(task)["project_id"],
                    )
                )
            elif tool == "cloud_submit":
                cloud = getattr(self, "codespaces", None)
                if cloud is None:
                    raise Blocked("Optional Codespaces integration is unavailable")
                result = cloud.submit_worker(task, request["id"], args)
                effect_started = True
            elif tool == "cloud_status":
                cloud = getattr(self, "codespaces", None)
                if cloud is None:
                    raise Blocked("Optional Codespaces integration is unavailable")
                if args.get("id"):
                    row = cloud.latest("cloud_job:" + cloud.name(args["id"]))
                    if not row or row["project"] != self.store.task(task)["project_id"]:
                        raise Blocked(
                            "Cloud job belongs to another project or does not exist"
                        )
                    cloud.reconcile(args["id"])
                result = {
                    "jobs": [
                        r
                        for r in cloud.jobs()
                        if r["project"] == self.store.task(task)["project_id"]
                    ]
                }
            elif tool == "list_files":
                result = {
                    "files": [
                        str(p.relative_to(root))
                        for p in root.rglob("*")
                        if p.is_file() and not p.is_symlink()
                    ][:2000]
                }
            elif tool == "read_file":
                p = scoped(root, args["path"])
                if p.stat().st_size > 2_000_000:
                    raise Blocked("Read bounded excerpts from large artifacts")
                result = {
                    "path": args["path"],
                    "sha256": file_hash(p),
                    "text": p.read_text("utf-8"),
                }
            elif tool == "write_file":
                p = scoped(root, args["path"])
                old = file_hash(p) if p.exists() else None
                if args.get("expected_hash") != old:
                    raise Conflict("File changed since proposal")
                if ("text" in args) == ("artifact" in args):
                    raise ContractError("Supply exactly one of text or artifact")
                data = (
                    args.get("text")
                    if "text" in args
                    else self.artifacts.read(
                        args["artifact"],
                        "worker",
                        self.store.task(task)["project_id"],
                        task=task,
                    )
                )
                if not isinstance(data, (str, bytes)):
                    raise ContractError("File contents must be text or artifact bytes")
                if len(data.encode() if isinstance(data, str) else data) > 2_000_000:
                    raise Blocked("Candidate file exceeds operation limit")
                # Content-addressed before/after artifacts survive an interrupted replacement.
                if p.exists():
                    self.artifacts.add(
                        p.read_bytes(), p.name, self.store.task(task)["project_id"]
                    )
                after = self.artifacts.add(
                    data, p.name, self.store.task(task)["project_id"]
                )
                self.store.put(
                    "file_intent",
                    request["id"],
                    {
                        "path": args["path"],
                        "before": old,
                        "after": after["sha256"],
                        "artifact": after["id"],
                    },
                )
                effect_started = True
                atomic_write(p, data)
                result = {
                    "path": args["path"],
                    "sha256": file_hash(p),
                    "artifact": after["id"],
                    "status": "saved",
                }
            elif tool == "checkpoint":
                result = {
                    "checkpoint": self.controller.checkpoint(
                        task,
                        args.get("reason", "worker checkpoint"),
                        args.get("next_action", ""),
                    )
                }
            elif tool == "read_artifact":
                data = self.artifacts.read(
                    args["artifact"],
                    "worker",
                    self.store.task(task)["project_id"],
                    task=task,
                )
                start, length = args.get("offset", 0), args.get("length", 32000)
                if (
                    type(start) is not int
                    or type(length) is not int
                    or start < 0
                    or not 1 <= length <= 64000
                ):
                    raise ContractError(
                        "Artifact excerpt requires nonnegative offset and 1–64000 bytes"
                    )
                import base64

                result = {
                    "artifact": args["artifact"],
                    "offset": start,
                    "total_bytes": len(data),
                    "encoding": "base64",
                    "data": base64.b64encode(data[start : start + length]).decode(),
                    "complete": start == 0 and length >= len(data),
                }
            elif tool == "verified_sources":
                # Rollback support: exact sources that passed a host comparison.
                result = self.verified_sources.listing(task, root, args.get("limit", 5))
            elif tool == "hosted_test_status":
                if args:
                    raise ContractError("hosted_test_status takes no arguments")
                project = self.store.task(task)["project_id"]
                result = {
                    "runs": [
                        {
                            k: r.get(k)
                            for k in (
                                "id",
                                "task_id",
                                "expected_sha",
                                "runner",
                                "status",
                                "remote_status",
                                "conclusion",
                                "run_id",
                                "run_url",
                                "error",
                                "artifacts",
                                "local_acceptance",
                            )
                        }
                        for r in self.hosted_tests.listing()
                        if r["project_id"] == project
                    ],
                    "claim": "Retained hosted workflow metadata, not local task acceptance",
                }
            elif tool == "test_programs":
                from .test_acceptance import NativeTestAcceptance

                contract = self.store.get("acceptance_contract", task)
                if contract["scope"] != "native_tool_tests" or args:
                    raise Blocked(
                        "test_programs runs only this task's pinned native test recipe, without arguments"
                    )
                verifier = NativeTestAcceptance(self.store)
                verifier.require_permission(self.store.task(task)["project_id"])
                effect_started = True
                result = verifier.verify(
                    root,
                    contract,
                    self.artifacts,
                    self.store.task(task)["project_id"],
                    self.context(task),
                )
                verifier.recheck(root, result)
            elif tool == "propose_workflow":
                from hivemind_assembly.learning.scopes import KnowledgeScopes

                KnowledgeScopes(self.store).check(task, "lesson", args["baseline"])
                if not self.domain or not hasattr(self.domain, "workflow_runner"):
                    raise Blocked("No executable workflow evaluator for this domain")
                from hivemind_assembly.learning.workflows import WorkflowLearning

                result = WorkflowLearning(
                    self.store, self.domain.workflow_runner()
                ).propose_variant(
                    task,
                    args["baseline"],
                    args["plan"],
                    args["evidence"],
                    request["id"],
                )
            elif tool == "run_workflow":
                from hivemind_assembly.learning.scopes import KnowledgeScopes

                KnowledgeScopes(self.store).check(task, "lesson", args["lesson"])
                if not self.domain or not hasattr(self.domain, "workflow_runner"):
                    raise Blocked("No executable workflow engine for this domain")
                from hivemind_assembly.learning.workflows import WorkflowLearning

                result = WorkflowLearning(
                    self.store, self.domain.workflow_runner()
                ).execute(args["lesson"], args.get("inputs", {}), external=True)
            elif tool == "link_repository" and self.repositories:
                if request["owner"] != "user.repository":
                    raise Blocked("Existing repositories must be selected by the owner")
                result = self.repositories.link(
                    self.store.task(task)["project_id"], request["id"], args
                )
                effect_started = True
            elif tool == "publish_checkpoint" and self.publications:
                result = self.publications.publish(
                    task, request["id"], args["validation"], root, cancel
                )
                effect_started = self.publications.uncertain(request["id"])
            elif tool == "create_repository" and self.repositories:
                result = self.repositories.create(
                    self.store.task(task)["project_id"], request["id"], args, cancel
                )
                effect_started = True
            elif tool == "repository_status" and self.repositories:
                result = self.repositories.status(self.store.task(task)["project_id"])
            elif self.domain:
                effect_started = tool in self.mutations
                result = self.domain.execute(self.context(task, tool), request)
            else:
                raise Blocked("Unknown capability")
            if self.publications:
                self.publications.record_checked_result(
                    task, request["id"], tool, args, result, root
                )
            self.verified_sources.retain(task, request["id"], tool, args, result, root)
            emitted = result.pop("_artifact", None)
            if emitted is not None:
                result["executable_artifact"] = self.artifacts.add(
                    emitted["data"],
                    emitted["name"],
                    self.store.task(task)["project_id"],
                )["id"]
            artifact = self.artifacts.add(
                canonical(result),
                request["id"] + ".json",
                self.store.task(task)["project_id"],
            )
            result["result_artifact"] = artifact["id"]
            result["operation_id"] = request["id"]
            self.controller.finish(request["id"], result, tool in self.mutations)
            self.controller.traces.append(
                task, request["id"], request["owner"], "tool_result", result
            )
            return result
        except BaseException as e:
            if tool in ("create_repository", "link_repository") and self.repositories:
                effect_started = self.repositories.uncertain(
                    self.store.task(task)["project_id"], request["id"]
                )
            if tool == "publish_checkpoint" and self.publications:
                effect_started = self.publications.uncertain(request["id"])
            self.controller.fail(request["id"], e, uncertain=effect_started)
            self.controller.traces.append(
                task,
                request["id"],
                request["owner"],
                "tool_error",
                {"error": str(e), "uncertain": effect_started},
            )
            raise

    def reconcile_file(self, op_id):
        op = self.store.one("SELECT * FROM operations WHERE id=?", (op_id,))
        if op["tool"] != "write_file" or op["state"] != "uncertain":
            raise ContractError("Not an uncertain file operation")
        intent = self.store.get("file_intent", op_id)
        p = scoped(self.workspace(op["task_id"]), intent["path"])
        current = file_hash(p) if p.exists() else None
        if current == intent["after"]:
            # Recovery under original epoch: no new writer can start until this completes.
            with self.store.tx() as c:
                task = dict(
                    c.execute(
                        "SELECT * FROM tasks WHERE id=?", (op["task_id"],)
                    ).fetchone()
                )
                if task["epoch"] != op["epoch"]:
                    raise Conflict("Recovery ownership changed")
                revision = c.execute(
                    "SELECT revision FROM projects WHERE id=?", (task["project_id"],)
                ).fetchone()[0]
                if revision != op["revision"]:
                    raise Conflict("Recovery revision changed")
                result = {"status": "saved", "sha256": current, "reconciled": True}
                c.execute(
                    "UPDATE operations SET state='saved',result=? WHERE id=?",
                    (canonical(result), op_id),
                )
                c.execute(
                    "UPDATE projects SET revision=revision+1 WHERE id=?",
                    (task["project_id"],),
                )
                c.execute("UPDATE tasks SET brief_id=NULL WHERE id=?", (task["id"],))
                self.store.event(
                    task["id"], "file_save_reconciled", {"operation": op_id}, c
                )
            return result
        if current == intent["before"]:
            self.controller.fail(
                op_id, "Confirmed not applied; a new operation may be proposed"
            )
            return {"status": "not_applied"}
        raise Conflict(
            "File differs from both recorded versions; preserve and investigate"
        )

    def reconcile_native(self, op_id):
        # Compatibility name; reconciliation policy now belongs to the domain.
        return self.reconcile_domain(op_id)

    def reconcile_domain(self, op_id):
        op = self.store.one("SELECT * FROM operations WHERE id=?", (op_id,))
        spec = self.capabilities.get(op["tool"])
        if (
            not (
                self.domain
                or (
                    op["tool"]
                    in ("create_repository", "link_repository", "publish_checkpoint")
                    and self.repositories
                )
            )
            or not spec
            or not spec.mutates_project
            or spec.recovery != "reconcile"
            or op["state"] != "uncertain"
        ):
            raise ContractError("Not an uncertain reconcilable domain mutation")
        if op["tool"] == "publish_checkpoint" and self.publications:
            observed = self.publications.reconcile(
                self.store.task(op["task_id"])["project_id"], op_id
            )
        elif (
            op["tool"] in ("create_repository", "link_repository") and self.repositories
        ):
            observed = self.repositories.reconcile(
                self.store.task(op["task_id"])["project_id"], op_id
            )
        else:
            observed = self.domain.reconcile(self.context(op["task_id"]), op)
        if observed.get("status") == "not_applied":
            self.controller.fail(
                op_id, "Domain evidence confirms operation was not applied"
            )
            return observed
        if observed.get("status") != "saved":
            raise Blocked("Domain has not confirmed a durable save")
        artifact = self.artifacts.add(
            canonical(observed),
            op_id + ".json",
            self.store.task(op["task_id"])["project_id"],
        )
        with self.store.tx() as c:
            task = dict(
                c.execute("SELECT * FROM tasks WHERE id=?", (op["task_id"],)).fetchone()
            )
            revision = c.execute(
                "SELECT revision FROM projects WHERE id=?", (task["project_id"],)
            ).fetchone()[0]
            if task["epoch"] != op["epoch"] or revision != op["revision"]:
                raise Conflict(
                    "Controller ownership or revision changed during reconciliation"
                )
            result = {
                **observed,
                "status": "saved",
                "reconciled": True,
                "operation_id": op_id,
                "result_artifact": artifact["id"],
            }
            c.execute(
                "UPDATE operations SET state='saved',result=? WHERE id=?",
                (canonical(result), op_id),
            )
            c.execute(
                "UPDATE projects SET revision=revision+1 WHERE id=?",
                (task["project_id"],),
            )
            c.execute("UPDATE tasks SET brief_id=NULL WHERE id=?", (task["id"],))
            self.store.event(
                task["id"], "operation_save_reconciled", {"operation": op_id}, c
            )
        return result

    def recover_pending(self):
        results = []
        for op in self.store.rows("SELECT * FROM operations WHERE state='uncertain'"):
            try:
                if op["tool"] == "write_file":
                    result = self.reconcile_file(op["id"])
                elif (
                    self.capabilities.get(op["tool"])
                    and self.capabilities[op["tool"]].recovery == "reconcile"
                ):
                    result = self.reconcile_domain(op["id"])
                elif (
                    self.capabilities.get(op["tool"])
                    and self.capabilities[op["tool"]].recovery == "discard"
                ):
                    self.controller.fail(
                        op["id"],
                        "Read-only computation interrupted; no result accepted",
                    )
                    result = {"status": "not_accepted"}
                else:
                    result = {
                        "status": "unresolved",
                        "reason": "External analysis process requires reconciliation",
                    }
                results.append({"operation": op["id"], **result})
            except Exception as error:
                results.append(
                    {
                        "operation": op["id"],
                        "status": "unresolved",
                        "reason": str(error),
                    }
                )
        return results
