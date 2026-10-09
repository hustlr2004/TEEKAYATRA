from __future__ import annotations

from locust import HttpUser, between, task


class TeekaReadUser(HttpUser):
    wait_time = between(0.2, 1.0)
    token = ""

    def on_start(self) -> None:
        response = self.client.post("/auth/login", json={"phone": "+918899999999", "password": "demo123"})
        if response.status_code == 200:
            self.token = response.json()["access_token"]

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer %s" % self.token} if self.token else {}

    @task(3)
    def children(self) -> None:
        self.client.get("/children?page=1&page_size=100&sort=id", headers=self.headers)

    @task(2)
    def villages(self) -> None:
        self.client.get("/villages?page=1&page_size=50&district=Load", headers=self.headers)

    @task(2)
    def schedule(self) -> None:
        self.client.get("/schedule?page=1&page_size=50", headers=self.headers)

    @task(2)
    def analytics(self) -> None:
        self.client.get("/analytics/manager?district=Load&page=1&page_size=20", headers=self.headers)

    @task(1)
    def leaderboard(self) -> None:
        self.client.get("/leaderboard/village?page=1&page_size=20", headers=self.headers)
