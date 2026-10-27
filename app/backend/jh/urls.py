import os

from django.urls import include, path, re_path

urlpatterns = [
    path("api/", include("core.urls")),
]

# Desktop shell serves the built SPA on the same origin as /api. Server deploy
# leaves JH_DESKTOP unset and keeps this module API-only (nginx serves the UI).
if os.environ.get("JH_DESKTOP") == "1":
    from jh.desktop_spa import spa

    urlpatterns += [re_path(r"^(?P<asset_path>.*)$", spa)]
