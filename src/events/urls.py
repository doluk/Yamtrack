from django.urls import path

from events import views

urlpatterns = [
    path("calendar", views.release_calendar, name="release_calendar"),
    path("reload_calendar", views.reload_calendar, name="reload_calendar"),
    path(
        "calendar/download/<str:token>",
        views.download_calendar,
        name="download_calendar",
    ),
]
