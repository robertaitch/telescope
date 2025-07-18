import asyncio
import threading
import os
from dataclasses import asdict
from telegram_checker import TelegramChecker

class TelegramCheckerWrapper:
    def __init__(self):
        self.api_id = None
        self.api_hash = None
        self.phone = None
        self.checker = TelegramChecker()
        self._loop = None
        self._thread = None
        self._lock = threading.Lock()

    def _ensure_loop(self):
        with self._lock:
            if self._loop is None or self._loop.is_closed():
                if self._thread and self._thread.is_alive():
                    self._thread.join(timeout=1)
                self._loop = asyncio.new_event_loop()

                def run_loop():
                    asyncio.set_event_loop(self._loop)
                    self._loop.run_forever()

                self._thread = threading.Thread(target=run_loop, daemon=True)
                self._thread.start()
        return self._loop

    def _run_in_loop(self, coro):
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=60)

    def set_config(self, api_id, api_hash, phone):
        self.api_id = int(api_id)
        self.api_hash = api_hash
        self.phone = phone
        self.checker.config['api_id'] = self.api_id
        self.checker.config['api_hash'] = self.api_hash
        self.checker.config['phone'] = self.phone

    def run_initialize(self):
        try:
            result = self._run_in_loop(self.checker.initialize())
            return result or not self.checker.needs_verification
        except Exception as e:
            print(f"Initialization error: {e}")
            return False

    def run_phone_check(self, phone):
        try:
            result = self._run_in_loop(self.checker.check_phone_number(phone))
            if result:
                result = asdict(result)
                result['profile_photos'] = [os.path.basename(p).replace("\\", "/") for p in result['profile_photos']]
            return result
        except Exception as e:
            print(f"Phone check error: {e}")
            return None

    def run_username_check(self, username):
        try:
            result = self._run_in_loop(self.checker.check_username(username))
            if result:
                result = asdict(result)
                result['profile_photos'] = [os.path.basename(p).replace("\\", "/") for p in result['profile_photos']]
            return result
        except Exception as e:
            print(f"Username check error: {e}")
            return None

    def needs_verification(self):
        return getattr(self.checker, "needs_verification", False)

    def submit_code(self, code):
        try:
            return self._run_in_loop(self.checker.submit_code(code))
        except Exception as e:
            print(f"Code submission error: {e}")
            raise e

    def cleanup(self):
        with self._lock:
            if self._loop and not self._loop.is_closed():
                self._loop.call_soon_threadsafe(self._loop.stop)
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=2)
