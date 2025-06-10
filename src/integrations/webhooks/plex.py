import json
import logging

from django.core.cache import cache
from django.utils import timezone

import app
import app.providers
from app.models import MediaTypes, Sources, Status

logger = logging.getLogger(__name__)


def process_payload(payload, user):
    """Process a Plex webhook payload."""
    logger.debug("Received Plex webhook payload: %s", json.dumps(payload, indent=2))
    event_type = payload.get("event")
    if not _is_supported_event(event_type):
        logger.info("Ignoring Plex webhook event type: %s", event_type)
        return

    if not _is_valid_user(payload, user):
        return

    ids = _extract_external_ids(payload)
    logger.debug("TMDB Episode ID: %s", ids["tmdb_id"])
    logger.debug("IMDB Episode ID: %s", ids["imdb_id"])
    logger.debug("TVDB Episode ID: %s", ids["tvdb_id"])

    media_type = _get_media_type(payload)
    if not media_type:
        logger.info("Ignoring Plex media type: %s", payload["Metadata"].get("type"))
        return

    if not any(ids.values()):
        logger.info("Ignoring Plex webhook call because no ID was found.")
        return

    if media_type == MediaTypes.TV.value:
        _process_tv(payload, user, ids)
    elif media_type == MediaTypes.MOVIE.value:
        _process_movie(payload, user, ids)


def _is_supported_event(event_type):
    return event_type in ("media.scrobble", "media.play")


def _is_valid_user(payload, user):
    incoming_username = payload["Account"]["title"].strip().lower()

    stored_usernames = [
        u.strip().lower() for u in (user.plex_usernames or "").split(",") if u.strip()
    ]

    is_valid = incoming_username in stored_usernames

    if not is_valid:
        logger.info(
            "Plex username %s does not match any of: %s",
            incoming_username,
            stored_usernames,
        )
    return is_valid


def _extract_external_ids(payload):
    guids = payload["Metadata"].get("Guid", [])

    def get_id(prefix):
        return next(
            (
                guid["id"].replace(f"{prefix}://", "")
                for guid in guids
                if guid["id"].startswith(f"{prefix}://")
            ),
            None,
        )

    return {
        "tmdb_id": get_id("tmdb"),
        "imdb_id": get_id("imdb"),
        "tvdb_id": get_id("tvdb"),
    }


def _get_media_type(payload):
    meta_type = payload["Metadata"].get("type")
    if meta_type == "episode":
        return MediaTypes.TV.value
    if meta_type == "movie":
        return MediaTypes.MOVIE.value
    return None


def _process_tv(payload, user, ids):
    title = payload["Metadata"]["grandparentTitle"]
    media_id, season_number, episode_number = _find_tv_media_id(ids)

    if not media_id:
        logger.info("No TMDB ID found for TV show: %s", title)
        return

    if not season_number or not episode_number:
        logger.info(
            "Could not match TV show episode for %s with TMDB ID %s",
            title,
            media_id,
        )
        return

    tvdb_id = app.providers.tmdb.tv_with_seasons(
        media_id,
        [season_number],
    )["tvdb_id"]

    if tvdb_id and user.anime_enabled:
        tvdb_id = int(tvdb_id)
        mapping_data = fetch_mapping_data()

        mal_id, episode_offset = get_mal_id_from_tvdb(
            mapping_data,
            tvdb_id,
            season_number,
            episode_number,
        )
        if mal_id:
            logger.info("Detected anime: %s", title)
            handle_anime(mal_id, episode_offset, payload, user)
            return

    logger.info("Detected TV show: %s", title)
    handle_tv_episode(media_id, season_number, episode_number, payload, user)


def _find_tv_media_id(ids):
    for ext_id, ext_type in [(ids["imdb_id"], "imdb_id"), (ids["tvdb_id"], "tvdb_id")]:
        if ext_id:
            response = app.providers.tmdb.find(ext_id, ext_type)
            logger.debug(
                "%s response: %s",
                ext_type.upper(),
                json.dumps(response, indent=2),
            )
            if (
                response.get("tv_episode_results")
                and len(response["tv_episode_results"]) > 0
            ):
                result = response["tv_episode_results"][0]
                show_id = result.get("show_id")
                season_number = result.get("season_number")
                episode_number = result.get("episode_number")
                return show_id, season_number, episode_number
    return None


def _process_movie(payload, user, ids):
    title = payload["Metadata"]["title"]
    if ids["tmdb_id"]:
        tmdb_id = int(ids["tmdb_id"])
        mapping_data = fetch_mapping_data()
        mal_id = get_mal_id_from_tmdb_movie(mapping_data, tmdb_id)
        if mal_id and user.anime_enabled:
            logger.info("Detected anime movie: %s", title)
            handle_anime(mal_id, 1, payload, user)
            return

        logger.info("Detected movie: %s", title)
        handle_movie(tmdb_id, payload, user)

    elif ids["imdb_id"]:
        response = app.providers.tmdb.find(ids["imdb_id"], "imdb_id")
        media_id = (
            response["movie_results"][0]["id"]
            if response.get("movie_results")
            else None
        )
        if media_id:
            logger.info("Detected movie: %s", title)
            handle_movie(media_id, payload, user)
        else:
            logger.info("No matching TMDB ID found for movie: %s", title)
    else:
        logger.info("No TMDB ID or IMDB ID found for movie: %s", title)


def handle_movie(media_id, payload, user):
    """Handle movie object from payload."""
    movie_metadata = app.providers.tmdb.movie(media_id)

    # Get or create the movie item
    movie_item, _ = app.models.Item.objects.get_or_create(
        media_id=media_id,
        source=Sources.TMDB.value,
        media_type=MediaTypes.MOVIE.value,
        defaults={
            "title": movie_metadata["title"],
            "image": movie_metadata["image"],
        },
    )

    movie_instances = app.models.Movie.objects.filter(
        item=movie_item,
        user=user,
    )

    current_instance = movie_instances.first()

    movie_played = payload["event"] == "media.scrobble"
    progress = 1 if movie_played else 0
    now = timezone.now().replace(second=0, microsecond=0)

    if current_instance and current_instance.status != Status.COMPLETED.value:
        current_instance.progress = progress

        if movie_played:
            current_instance.end_date = now
            current_instance.status = Status.COMPLETED.value
        elif current_instance.status != Status.IN_PROGRESS.value:
            current_instance.start_date = now
            current_instance.status = Status.IN_PROGRESS.value
        current_instance.save()
    else:
        app.models.Movie.objects.create(
            item=movie_item,
            user=user,
            progress=progress,
            status=Status.COMPLETED.value if movie_played else Status.IN_PROGRESS.value,
            start_date=now if not movie_played else None,
            end_date=now if movie_played else None,
        )

    logger.info(
        "Marked movie as %s for user %s: %s",
        "played" if movie_played else "in progress",
        user.username,
        movie_metadata["title"],
    )


def handle_tv_episode(media_id, season_number, episode_number, payload, user):
    """Add a TV show episode as watched."""
    tv_metadata = app.providers.tmdb.tv_with_seasons(
        media_id,
        [season_number],
    )
    season_metadata = tv_metadata[f"season/{season_number}"]

    tv_item, _ = app.models.Item.objects.get_or_create(
        media_id=media_id,
        source=Sources.TMDB.value,
        media_type=MediaTypes.TV.value,
        defaults={
            "title": tv_metadata["title"],
            "image": tv_metadata["image"],
        },
    )

    tv_instance, created = app.models.TV.objects.get_or_create(
        item=tv_item,
        user=user,
        defaults={
            "status": Status.IN_PROGRESS.value,
        },
    )

    if created:
        logger.info(
            "Created new TV instance for user %s: %s",
            user.username,
            tv_metadata["title"],
        )
    elif not created and tv_instance.status not in (
        Status.COMPLETED.value,
        Status.IN_PROGRESS.value,
    ):
        tv_instance.status = Status.IN_PROGRESS.value
        tv_instance.save()
        logger.info(
            "Updated TV instance for user %s: %s (status: %s)",
            user.username,
            tv_metadata["title"],
            tv_instance.status,
        )

    season_item, _ = app.models.Item.objects.get_or_create(
        media_id=media_id,
        source=Sources.TMDB.value,
        media_type=MediaTypes.SEASON.value,
        season_number=season_number,
        defaults={
            "title": tv_metadata["title"],
            "image": season_metadata["image"],
        },
    )

    season_instance, created = app.models.Season.objects.get_or_create(
        item=season_item,
        user=user,
        related_tv=tv_instance,
        defaults={
            "status": Status.IN_PROGRESS.value,
        },
    )

    if created:
        logger.info(
            "Created new season instance for user %s: %s S%d",
            user.username,
            tv_metadata["title"],
            season_number,
        )
    elif not created and season_instance.status not in (
        Status.COMPLETED.value,
        Status.IN_PROGRESS.value,
    ):
        season_instance.status = Status.IN_PROGRESS.value
        season_instance.save()
        logger.info(
            "Updated season instance for user %s: %s %d (status: %s)",
            user.username,
            tv_metadata["title"],
            season_number,
            season_instance.status,
        )

    episode_item, _ = app.models.Item.objects.get_or_create(
        media_id=media_id,
        source=Sources.TMDB.value,
        media_type=MediaTypes.EPISODE.value,
        season_number=season_number,
        episode_number=episode_number,
        defaults={
            "title": tv_metadata["title"],
            "image": season_metadata["image"],
        },
    )

    episode_played = payload["event"] == "media.scrobble"

    if episode_played:
        now = timezone.now().replace(second=0, microsecond=0)
        app.models.Episode.objects.create(
            item=episode_item,
            related_season=season_instance,
            end_date=now,
        )

        logger.info(
            "Marked episode as played for user %s: %s S%d E%d",
            user.username,
            tv_metadata["title"],
            season_number,
            episode_number,
        )


def handle_anime(media_id, episode_number, payload, user):
    """Add an anime episode as watched."""
    anime_metadata = app.providers.mal.anime(media_id)
    anime_item, _ = app.models.Item.objects.get_or_create(
        media_id=media_id,
        source=Sources.MAL.value,
        media_type=MediaTypes.ANIME.value,
        defaults={
            "title": anime_metadata["title"],
            "image": anime_metadata["image"],
        },
    )

    anime_instances = app.models.Anime.objects.filter(
        item=anime_item,
        user=user,
    )

    current_instance = anime_instances.first()

    episode_played = payload["event"] == "media.scrobble"
    if not episode_played:
        episode_number = max(0, episode_number - 1)

    if current_instance and current_instance.status != Status.COMPLETED.value:
        current_instance.progress = episode_number
        current_instance.status = Status.IN_PROGRESS.value
        current_instance.save()
    else:
        app.models.Anime.objects.create(
            item=anime_item,
            user=user,
            progress=episode_number,
            status=Status.IN_PROGRESS.value,
        )


def fetch_mapping_data():
    """Fetch the anime mapping data from GitHub."""
    data = cache.get("jellyfin_anime_mapping")

    if data is None:
        url = "https://raw.githubusercontent.com/Kometa-Team/Anime-IDs/refs/heads/master/anime_ids.json"
        data = app.providers.services.api_request("GITHUB", "GET", url)
        cache.set("jellyfin_anime_mapping", data)

    return data


def get_mal_id_from_tvdb(mapping_data, tvdb_id, season_number, episode_number):
    """Find the appropriate MAL ID based on TVDB id."""
    matching_entries = [
        entry
        for entry in mapping_data.values()
        if entry.get("tvdb_id") == tvdb_id
        and entry.get("tvdb_season") == season_number
        and "mal_id" in entry
    ]

    if not matching_entries:
        return None, None

    # Sort entries by epoffset
    matching_entries.sort(key=lambda x: x.get("tvdb_epoffset", 0))

    # Find the appropriate entry based on episode number
    for i, entry in enumerate(matching_entries):
        current_offset = entry.get("tvdb_epoffset", 0)
        next_offset = float("inf")

        if i < len(matching_entries) - 1:
            next_offset = matching_entries[i + 1].get("tvdb_epoffset", float("inf"))

        if episode_number > current_offset and (
            episode_number <= next_offset or next_offset == float("inf")
        ):
            return entry["mal_id"], episode_number - current_offset

    return None, None


def get_mal_id_from_tmdb_movie(mapping_data, tmdb_movie_id):
    """Find the MAL ID for a given TMDB movie ID."""
    for entry in mapping_data.values():
        if entry.get("tmdb_movie_id") == tmdb_movie_id and "mal_id" in entry:
            return entry["mal_id"]
    return None
