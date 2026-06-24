from .server import main

if __name__ == "__main__":
    # Click will handle CLI arguments
    import sys

    sys.exit(main())  # type: ignore[call-arg]
