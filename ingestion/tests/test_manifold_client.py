import httpx
from bellwether_ingestion.manifold.client import ManifoldClient


def test_iter_bets_paginates_and_stops():
    pages = {
        None: [{"id": "b1"}, {"id": "b2"}],
        "b2": [{"id": "b3"}],
        "b3": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        before = request.url.params.get("before")
        return httpx.Response(200, json=pages[before])

    transport = httpx.MockTransport(handler)
    client = ManifoldClient()
    client._client.close()
    client._client = httpx.Client(transport=transport)

    got = list(client.iter_bets(user_id="u1", page_size=2, max_pages=10))
    assert [b["id"] for b in got] == ["b1", "b2", "b3"]


def test_iter_bets_stops_when_batch_smaller_than_page_size():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"id": "only"}])

    transport = httpx.MockTransport(handler)
    client = ManifoldClient()
    client._client.close()
    client._client = httpx.Client(transport=transport)

    got = list(client.iter_bets(user_id="u1", page_size=10, max_pages=5))
    assert [b["id"] for b in got] == ["only"]
