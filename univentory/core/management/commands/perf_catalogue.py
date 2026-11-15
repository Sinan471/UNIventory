"""Baseline catalogue performance check (NFR-01).

Runs at least 200 measured catalogue/search/list requests after warm-up
with 20 concurrent signed-in clients through the full Django stack
(middleware, access policy, queries, templates). It excludes network,
identity-provider and AI time, as NFR-01 specifies.

This is a development baseline. The acceptance measurement must be repeated
on the recorded reference host (docs/OPERATIONS.md) and reported with the
host details; a local run is not acceptance evidence.
"""
import random
import statistics
import threading
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.test import Client

from catalogue.models import Listing, ListingState
from identity.models import AppUser, Category


class Command(BaseCommand):
    help = "Measure catalogue p95 latency with concurrent signed-in clients."

    def add_arguments(self, parser):
        parser.add_argument("--users", type=int, default=20)
        parser.add_argument("--requests", type=int, default=200)
        parser.add_argument("--warmup", type=int, default=20)
        parser.add_argument("--username", default="sara.requester")

    def handle(self, *args, **opts):
        if "testserver" not in settings.ALLOWED_HOSTS:
            settings.ALLOWED_HOSTS.append("testserver")
        user = AppUser.objects.filter(username=opts["username"]).first()
        if user is None:
            raise CommandError("User not found. Run seed_demo first or pass --username.")
        listings = list(Listing.objects.filter(state=ListingState.PUBLISHED).values_list("pk", flat=True)[:200])
        categories = list(Category.objects.values_list("pk", flat=True))
        if not listings:
            raise CommandError("No published listings. Run seed_demo --assets 1000 first.")
        rng = random.Random(7)

        def urls():
            return [
                "/exchange/",
                f"/exchange/?q={rng.choice(['chair', 'laptop', 'microscope', 'projector', 'drill'])}",
                f"/exchange/?category={rng.choice(categories)}&sort=free",
                f"/exchange/?view=list&availability=all&page={rng.randint(1, 3)}",
                f"/exchange/listings/{rng.choice(listings)}/",
            ]

        clients = []
        for _ in range(opts["users"]):
            client = Client()
            client.force_login(user, backend="identity.backends.UniversityIdentityBackend")
            clients.append(client)
        for i in range(opts["warmup"]):
            clients[i % len(clients)].get(rng.choice(urls()))

        timings: list[float] = []
        errors = 0
        lock = threading.Lock()
        per_user = max(1, -(-opts["requests"] // opts["users"]))

        def worker(client):
            nonlocal errors
            local_rng = random.Random(id(client))
            for _ in range(per_user):
                url = local_rng.choice(urls())
                start = time.perf_counter()
                response = client.get(url)
                elapsed = time.perf_counter() - start
                with lock:
                    timings.append(elapsed)
                    if response.status_code >= 400:
                        errors += 1

        threads = [threading.Thread(target=worker, args=(c,)) for c in clients]
        start = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        wall = time.perf_counter() - start
        timings.sort()
        p95 = timings[int(len(timings) * 0.95) - 1]
        assets = Listing.objects.values("asset").distinct().count()
        self.stdout.write(
            f"requests={len(timings)} users={opts['users']} published_listings={assets} wall={wall:.1f}s\n"
            f"p50={statistics.median(timings) * 1000:.0f}ms p95={p95 * 1000:.0f}ms max={timings[-1] * 1000:.0f}ms "
            f"errors={errors} ({errors / len(timings):.1%})"
        )
        target = 2.0
        style = self.style.SUCCESS if p95 <= target and errors == 0 else self.style.ERROR
        self.stdout.write(style(f"NFR-01 target p95 <= {target:.0f}s: {'met' if p95 <= target else 'NOT met'} "
                                "on this host (development baseline only)."))
