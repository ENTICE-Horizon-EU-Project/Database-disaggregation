"""Export a saved MARIO MRIO checkpoint to GDX, with exact cell-by-cell read-back."""
import argparse
from pathlib import Path
from database_disaggregation.reporting.saved_gdx import export_saved_gdx

if __name__ == '__main__':
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--database',type=Path,required=True)
    cli.add_argument('--output',type=Path)
    cli.add_argument('--system-directory',type=Path,help='GAMS installation directory, if not on the default search path.')
    cli.add_argument('--overwrite',action='store_true')
    args=cli.parse_args()
    export_saved_gdx(args.database,args.output,system_directory=args.system_directory,overwrite=args.overwrite)
