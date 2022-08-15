import typer
from sentential.lib.local import Repository, Image, Lambda

local = typer.Typer()


@local.command()
def deploy(
    tag: str = typer.Argument("latest", envvar="TAG"),
    public_url: bool = typer.Option(default=False),
):
    Lambda(Image(tag)).deploy(public_url)


@local.command()
def destroy(
    tag: str = typer.Argument("latest", envvar="TAG"),
):
    Lambda(Image(tag)).destroy()
