"""Testes de liveness (/health) e readiness (/ready) — separação feita
para o healthCheckPath do Render (bate em /health com frequência maior
que os 5 minutos de ociosidade que fariam o compute do Neon escalar a
zero) parar de consultar o banco a cada chamada (auditoria de consumo
de CU-h, set/2026). /health nunca deve abrir conexão com o banco;
/ready preserva a verificação real (SELECT 1) que /health fazia antes.

Precisa de um PostgreSQL real (mesma regra dos demais testes desta
suíte — nunca SQLite como referência), só para o teste de /ready com
banco acessível; o teste de /health nunca toca o banco de verdade
(SessionLocal é mockado nele).

Uso:
    DATABASE_URL=postgresql://usuario:senha@localhost/sigab_teste \
    SECRET_KEY=qualquer-coisa-com-32-caracteres-ou-mais \
    AMBIENTE=local \
    python3 -m unittest tests.test_health -v
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import health, ready  # noqa: E402


class TesteHealthLiveness(unittest.TestCase):
    @patch("main.SessionLocal")
    def test_health_retorna_200_sem_acessar_banco(self, mock_session_local):
        resposta = health()

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.body, b'{"status":"ok"}')
        mock_session_local.assert_not_called()


class TesteReadyReadiness(unittest.TestCase):
    def test_ready_retorna_200_quando_banco_acessivel(self):
        resposta = ready()

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.body, b'{"status":"ok"}')

    @patch("main.SessionLocal")
    def test_ready_retorna_503_quando_banco_indisponivel(self, mock_session_local):
        mock_session_local.side_effect = RuntimeError("conexão recusada")

        resposta = ready()

        self.assertEqual(resposta.status_code, 503)
        self.assertEqual(resposta.body, b'{"status":"erro"}')


if __name__ == "__main__":
    unittest.main()
