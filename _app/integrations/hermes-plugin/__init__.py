"""Install as a Hermes plugin with the workbench _app directory on PYTHONPATH.
No model-provider substitution: this command runs native-browser sessions only.
"""


def register(ctx):
    def setup(parser):
        parser.add_argument("--data-dir", default=None)
        parser.add_argument("--port", type=int, default=0)

    def run(args):
        from hivemind_assembly.application.app import serve, data_home

        serve(args.data_dir or data_home(), args.port)

    ctx.register_cli_command("workbench", "Start Hivemind Assembly", setup, run)
