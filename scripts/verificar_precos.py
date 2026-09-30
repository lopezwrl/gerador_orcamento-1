import json
import logging

from orcatech.app import app
from orcatech.monitoramento_service import verificar_precos


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    resultado = verificar_precos(app)
    print(json.dumps(resultado, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
