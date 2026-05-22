"""
tracker.py - Rastreamento de ocorrências de erros e detecção de duplicatas
"""

import json
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Arquivo onde o estado é persistido entre reinicializações
STATE_FILE = "occurrences_state.json"


class OccurrenceTracker:
    """
    Rastreia ocorrências de erros por (conjunto, erro).
    Dispara alerta quando o mesmo par aparece >= MIN_OCCURRENCES vezes
    dentro da janela de tempo configurada.
    """

    def __init__(
        self,
        window_hours: int = 24,
        min_occurrences: int = 2,
        state_file: str = STATE_FILE,
    ):
        self.window_hours = window_hours
        self.min_occurrences = min_occurrences
        self.state_file = state_file

        # Estrutura: { "chave": [ {"ts": "iso", "subject": "...", "msg_id": "..."}, ... ] }
        self._data: Dict[str, List[dict]] = {}
        # Conjunto de chaves que já geraram alerta (para não re-alertar infinitamente)
        self._alerted: Dict[str, str] = {}  # chave -> timestamp do alerta

        self._load_state()

    # ------------------------------------------------------------------
    # Persistência
    # ------------------------------------------------------------------

    def _load_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    self._data = saved.get("data", {})
                    self._alerted = saved.get("alerted", {})
                logger.info(f"Estado carregado de '{self.state_file}'")
            except Exception as e:
                logger.warning(f"Não foi possível carregar estado: {e}")
                self._data = {}
                self._alerted = {}

    def _save_state(self):
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump({"data": self._data, "alerted": self._alerted}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Erro ao salvar estado: {e}")

    # ------------------------------------------------------------------
    # Lógica principal
    # ------------------------------------------------------------------

    @staticmethod
    def _make_key(conjunto: str, erro: str) -> str:
        """Chave normalizada para (conjunto, erro)."""
        return f"{conjunto.strip().lower()}||{erro.strip().lower()}"

    def _purge_old_entries(self, key: str):
        """Remove entradas fora da janela de tempo."""
        if key not in self._data:
            return
        cutoff = datetime.utcnow() - timedelta(hours=self.window_hours)
        self._data[key] = [
            e for e in self._data[key]
            if datetime.fromisoformat(e["ts"]) >= cutoff
        ]
        if not self._data[key]:
            del self._data[key]
            # Se não há mais ocorrências na janela, reseta o alerta enviado
            if key in self._alerted:
                alerted_ts = datetime.fromisoformat(self._alerted[key])
                if alerted_ts < cutoff:
                    del self._alerted[key]
                    logger.debug(f"Alerta resetado para chave: {key}")

    def register(
        self,
        conjunto: str,
        erro: str,
        subject: str = "",
        msg_id: str = "",
    ) -> Tuple[bool, int]:
        """
        Registra uma ocorrência de (conjunto, erro).

        Retorna:
            (deve_alertar: bool, total_ocorrencias: int)
        """
        key = self._make_key(conjunto, erro)
        self._purge_old_entries(key)

        entry = {
            "ts": datetime.utcnow().isoformat(),
            "subject": subject,
            "msg_id": msg_id,
        }

        if key not in self._data:
            self._data[key] = []
        self._data[key].append(entry)

        total = len(self._data[key])
        logger.info(f"Ocorrência registrada [{total}x] → conjunto='{conjunto}' | erro='{erro}'")

        # Verifica se deve disparar alerta
        deve_alertar = (
            total >= self.min_occurrences
            and key not in self._alerted
        )

        if deve_alertar:
            self._alerted[key] = datetime.utcnow().isoformat()
            logger.warning(f"ALERTA DISPARADO → conjunto='{conjunto}' | erro='{erro}' | ocorrências={total}")

        self._save_state()
        return deve_alertar, total

    def get_occurrences(self, conjunto: str, erro: str) -> List[dict]:
        """Retorna todas as ocorrências na janela atual para (conjunto, erro)."""
        key = self._make_key(conjunto, erro)
        self._purge_old_entries(key)
        return self._data.get(key, [])

    def reset_alert(self, conjunto: str, erro: str):
        """Reseta manualmente o alerta de um par (conjunto, erro)."""
        key = self._make_key(conjunto, erro)
        if key in self._alerted:
            del self._alerted[key]
            self._save_state()
            logger.info(f"Alerta resetado manualmente para: conjunto='{conjunto}' | erro='{erro}'")

    def summary(self) -> List[dict]:
        """Retorna resumo de todos os pares ativos com contagem."""
        result = []
        for key, entries in self._data.items():
            parts = key.split("||", 1)
            result.append({
                "conjunto": parts[0] if len(parts) > 0 else key,
                "erro": parts[1] if len(parts) > 1 else "",
                "ocorrencias": len(entries),
                "primeiro": entries[0]["ts"] if entries else None,
                "ultimo": entries[-1]["ts"] if entries else None,
                "alerta_enviado": key in self._alerted,
            })
        return sorted(result, key=lambda x: x["ocorrencias"], reverse=True)
        