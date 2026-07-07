"""
tracker.py - Rastreamento de ocorrências de erros e detecção de duplicatas
"""

import json
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

STATE_FILE = "occurrences_state.json"


class OccurrenceTracker:

    def __init__(
        self,
        window_hours: int = 24,
        min_occurrences: int = 2,
        state_file: str = STATE_FILE,
        cleanup_interval_days: int = 30,
    ):
        self.window_hours = window_hours
        self.min_occurrences = min_occurrences
        self.state_file = state_file
        self.cleanup_interval_days = cleanup_interval_days

        self._data: Dict[str, List[dict]] = {}
        self._alerted: Dict[str, str] = {}  # chave -> timestamp do último alerta
        self._last_cleanup: Optional[str] = None

        self._load_state()

    def _load_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    self._data = saved.get("data", {})
                    self._alerted = saved.get("alerted", {})
                    self._last_cleanup = saved.get("last_cleanup")
                logger.info(f"Estado carregado de '{self.state_file}'")
            except Exception as e:
                logger.warning(f"Não foi possível carregar estado: {e}")
                self._data = {}
                self._alerted = {}

    def _save_state(self):
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "data": self._data,
                        "alerted": self._alerted,
                        "last_cleanup": self._last_cleanup,
                    },
                    f, ensure_ascii=False, indent=2,
                )
        except Exception as e:
            logger.error(f"Erro ao salvar estado: {e}")

    @staticmethod
    def _make_key(conjunto: str, erro: str) -> str:
        return f"{conjunto.strip().lower()}||{erro.strip().lower()}"

    def _purge_old_entries(self, key: str):
        if key not in self._data:
            return
        cutoff = datetime.utcnow() - timedelta(hours=self.window_hours)
        self._data[key] = [
            e for e in self._data[key]
            if datetime.fromisoformat(e["ts"]) >= cutoff
        ]
        if not self._data[key]:
            del self._data[key]
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

        # Antes, uma vez que "key in self._alerted" virava True, o alerta
        # nunca mais disparava de novo para essa combinação (conjunto+erro),
        # mesmo que ela voltasse a ocorrer dias/semanas depois - o flag só
        # era removido quando TODAS as ocorrências saíam da janela, o que
        # não acontecia enquanto o erro continuava se repetindo.
        #
        # Agora, em vez de "já alertou uma vez, nunca mais alerta", conta-se
        # quantas ocorrências NOVAS aconteceram desde o último alerta. Ao
        # atingir min_occurrences de novo, um novo alerta é disparado -
        # ou seja, o alerta pode repetir quantas vezes o erro realmente
        # voltar a se repetir, e não só uma vez na vida da automação.
        last_alert_ts = self._alerted.get(key)
        if last_alert_ts:
            last_alert_dt = datetime.fromisoformat(last_alert_ts)
            novas_desde_alerta = [
                e for e in self._data[key]
                if datetime.fromisoformat(e["ts"]) > last_alert_dt
            ]
            contagem_para_alerta = len(novas_desde_alerta)
        else:
            contagem_para_alerta = total

        deve_alertar = contagem_para_alerta >= self.min_occurrences

        if deve_alertar:
            self._alerted[key] = datetime.utcnow().isoformat()
            logger.warning(
                f"ALERTA DISPARADO → conjunto='{conjunto}' | erro='{erro}' | "
                f"ocorrências totais na janela={total} | novas desde último alerta={contagem_para_alerta}"
            )

        self._save_state()
        return deve_alertar, total

    def get_occurrences(self, conjunto: str, erro: str) -> List[dict]:
        key = self._make_key(conjunto, erro)
        self._purge_old_entries(key)
        return self._data.get(key, [])

    def reset_alert(self, conjunto: str, erro: str):
        key = self._make_key(conjunto, erro)
        if key in self._alerted:
            del self._alerted[key]
            self._save_state()
            logger.info(f"Alerta resetado manualmente para: conjunto='{conjunto}' | erro='{erro}'")

    def run_maintenance(self, force: bool = False) -> bool:
        """Faz uma limpeza geral do estado (occurrences_state.json).

        Diferente de _purge_old_entries (que só limpa UMA chave, e só
        quando aquele mesmo conjunto+erro volta a ocorrer), esta rotina
        varre TODAS as chaves. Isso é necessário porque um conjunto que
        parou de dar erro nunca mais aciona register()/get_occurrences()
        para sua chave - ela ficaria presa no arquivo de estado para
        sempre, fazendo o arquivo crescer sem limite e degradando a
        performance com o tempo.

        Roda automaticamente a cada `cleanup_interval_days` dias (padrão
        30, alinhado ao maior período de recorrência de erro configurado).
        Retorna True se a limpeza foi executada nesta chamada.
        """
        now = datetime.utcnow()

        if not force and self._last_cleanup:
            try:
                ultima = datetime.fromisoformat(self._last_cleanup)
                if now - ultima < timedelta(days=self.cleanup_interval_days):
                    return False
            except Exception:
                pass  # timestamp inválido no state.json - força a limpeza agora

        cutoff = now - timedelta(hours=self.window_hours)

        chaves_removidas = 0
        for key in list(self._data.keys()):
            self._data[key] = [
                e for e in self._data[key]
                if datetime.fromisoformat(e["ts"]) >= cutoff
            ]
            if not self._data[key]:
                del self._data[key]
                chaves_removidas += 1

        # Remove alertas "órfãos": chaves que não têm mais nenhuma
        # ocorrência dentro da janela (o erro parou de acontecer).
        alertas_removidos = 0
        for key in list(self._alerted.keys()):
            if key not in self._data:
                del self._alerted[key]
                alertas_removidos += 1

        self._last_cleanup = now.isoformat()
        self._save_state()

        logger.info(
            f"Manutenção do estado executada: {chaves_removidas} chave(s) expirada(s) "
            f"e {alertas_removidos} alerta(s) órfão(s) removido(s). "
            f"Próxima manutenção em ~{self.cleanup_interval_days} dias."
        )
        return True

    def summary(self) -> List[dict]:
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