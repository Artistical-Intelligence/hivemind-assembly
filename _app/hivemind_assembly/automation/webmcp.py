"""Use documented, page-registered native UI actions when available.

This is the public document.modelContext API, not a private provider endpoint or
inference API. Only a fixed set of ordinary conversation actions is eligible.
The caller owns durable send intent and never falls back after a dispatched call.
"""

import json
from hivemind_assembly.core.common import Blocked

ALLOWED = {
    "get_conversation_state": set(),
    "submit_conversation_message": {"prompt"},
    "start_conversation": set(),
}


class NativeUI:
    def __init__(self, page):
        self.page = page

    async def available(self, name):
        if name not in ALLOWED:
            return False
        return await self.page.evaluate(
            """async name => {
          const api=document.modelContext;
          if(!api || typeof api.getTools!=='function' || typeof api.executeTool!=='function') return false;
          const tools=await api.getTools();
          const matches=tools.filter(t=>(t.name===name || t.name.startsWith(name+'__')) && t.origin===location.origin);
          return matches.length===1;
        }""",
            name,
        )

    async def call(self, name, arguments):
        if name not in ALLOWED or set(arguments) != ALLOWED[name]:
            raise Blocked("Unrecognized native UI action")
        result = await self.page.evaluate(
            """async ({name,args}) => {
          const api=document.modelContext;
          if(!api || typeof api.getTools!=='function') throw Error('Native UI tools unavailable');
          const tools=await api.getTools();
          const matches=tools.filter(t=>(t.name===name || t.name.startsWith(name+'__')) && t.origin===location.origin);
          if(matches.length!==1) throw Error('Native UI tool changed or is ambiguous');
          const tool=matches[0], schema=tool.inputSchema;
          if(!schema || schema.type!=='object' || Object.keys(args).some(k=>!(k in (schema.properties||{}))))
            throw Error('Native UI action schema changed');
          return await api.executeTool(tool,args);
        }""",
            {"name": name, "args": arguments},
        )
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except ValueError:
                return {"raw": result}
        if isinstance(result, dict) and result.get("isError"):
            raise Blocked(
                "Native UI action returned an error; reconcile before retrying"
            )
        return result
