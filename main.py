"""Point d'entrée de la webapp Cartes de grêle."""

import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "backend.app:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8010")),
        reload=os.environ.get("RELOAD", "false").lower() == "true",
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
    )
