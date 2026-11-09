import os,sys

def main():
    if len(sys.argv)>=2 and sys.argv[1]=='--smoke-test':
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from aicad.smoke import run
        output=sys.argv[2] if len(sys.argv)>2 else 'smoke_output'
        run(output)
        return 0
    if len(sys.argv)>=2 and sys.argv[1]=='--legacy-ui':
        from aicad.ui import main as start_legacy
        return start_legacy()
    from aicad.universal_ui import main as start_ui
    return start_ui()

if __name__=='__main__':sys.exit(main())
