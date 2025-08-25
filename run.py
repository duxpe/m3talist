from rich import print
from src.app import prepare_input_files_for_playlist, prepare_paths

print("Welcome to")
print("""[yellow]▖  ▖▄▖▄▖▄▖▖ ▄▖▄▖▄▖
▛▖▞▌▄▌▐ ▌▌▌ ▐ ▚ ▐ 
▌▝ ▌▄▌▐ ▛▌▙▖▟▖▄▌▐[/yellow]""")

print("Preparing paths...")
prepare_paths()

print("""[bold green]Choose the number of a mode for processing[/bold green]:\n
      0 - Keep original artists, choose only album name.\n
      1 - Choose artists and album names.""")

mode = -1

while mode not in (0, 1):
    mode = int(input())
    if mode not in (0, 1):
        print("""[red]invalid option[/red], 
              type either [green]0[/green] or [green]1[/green]""")

prepare_input_files_for_playlist(mode=mode)
