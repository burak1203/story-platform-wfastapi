import asyncio
from collections import defaultdict


class SseBroker:
    """Ayni process icindeki basit yayin/abonelik koprusu.

    Uretim task'lari publish eder; /stream ucundaki her acik baglanti kendi
    kuyrugundan okur. Coklu instance'a gecilirse Redis pub/sub ile degistirilir.
    """

    def __init__(self) -> None:
        self._subscribers: dict[int, set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, story_id: int) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=32)
        self._subscribers[story_id].add(queue)
        return queue

    def unsubscribe(self, story_id: int, queue: asyncio.Queue) -> None:
        subs = self._subscribers.get(story_id)
        if subs is not None:
            subs.discard(queue)
            if not subs:
                self._subscribers.pop(story_id, None)

    def publish(self, story_id: int, data: dict) -> None:
        for queue in list(self._subscribers.get(story_id, ())):
            try:
                queue.put_nowait(data)
            except asyncio.QueueFull:
                # Okumayan aboneyi bekletmek yerine mesaji dusuruyoruz;
                # istemci zaten yeniden baglandiginda guncel durumu fetch ediyor.
                pass


broker = SseBroker()
