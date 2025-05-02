import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from django.core.cache import cache
from django.db.models import Count, Exists, OuterRef, Q, Subquery
from django.utils import timezone

from app import media_type_config
from app.models import Item, MediaTypes, Sources
from app.providers import comicvine, services, tmdb
from events.models import Event, SentinelDatetime

logger = logging.getLogger(__name__)


def fetch_releases(user=None, items_to_process=None):
    """Fetch and process releases for the calendar."""
    if items_to_process and items_to_process[0].source == Sources.MANUAL.value:
        return "Manual sources are not processed"

    if not items_to_process:
        items_to_process = get_items_to_process(user)

    if not items_to_process:
        return "No items to process"

    events_bulk = []
    anime_to_process = []

    for item in items_to_process:
        # anime can later be processed in bulk
        if item.media_type == MediaTypes.ANIME.value:
            anime_to_process.append(item)
        elif item.media_type == MediaTypes.TV.value:
            process_tv(item, events_bulk)
        elif item.media_type == MediaTypes.COMIC.value:
            process_comic(item, events_bulk)
        else:
            process_other(item, events_bulk)

    process_anime_bulk(anime_to_process, events_bulk)

    for event in events_bulk:
        Event.objects.update_or_create(
            item=event.item,
            content_number=event.content_number,
            defaults={"datetime": event.datetime},
        )

    cleanup_invalid_events(events_bulk)

    result_msg = "\n".join(
        f"{item} ({item.get_media_type_display()})" for item in items_to_process
    )

    if len(items_to_process) > 0:
        return f"""Releases have been fetched for the following items:
                    {result_msg}"""
    return "No releases have been fetched for any items."


def cleanup_invalid_events(events_bulk):
    """Remove events that are no longer valid based on updated items."""
    processed_items = {}

    for event in events_bulk:
        if event.content_number is not None:
            try:
                processed_items[event.item.id].add(event.content_number)
            except KeyError:
                processed_items[event.item.id] = {event.content_number}

    all_events = Event.objects.filter(
        item_id__in=processed_items.keys(),
    ).select_related("item")

    events_to_delete = []

    for event in all_events:
        if (
            event.content_number is not None
            and event.item_id in processed_items
            and event.content_number not in processed_items[event.item_id]
        ):
            logger.info(
                "Invalid event detected: %s - Number %s (scheduled for %s)",
                event.item,
                event.content_number,
                event.datetime,
            )
            events_to_delete.append(event.id)

    if events_to_delete:
        deleted_count = Event.objects.filter(id__in=events_to_delete).delete()[0]
        logger.info("Deleted %s invalid events for updated items", deleted_count)


def get_items_to_process(user=None):
    """Get items to process for the calendar.

    This function identifies items that need calendar events by:
    1. Finding active items (non-inactive status)
    2. Replacing season items with their parent TV shows
    3. Including items with no events or future events
    4. Including comics with recent events
    """
    active_items = get_active_items(user)

    items_needing_events = filter_items_needing_events(active_items)

    return replace_seasons_with_tv_shows(items_needing_events)


def get_active_items(user=None):
    """Get all items, excluding manual sources."""
    media_types = [
        choice.value
        for choice in MediaTypes
        if choice not in [MediaTypes.TV, MediaTypes.EPISODE]
    ]

    active_query = Q()

    for media_type in media_types:
        # Build query for this media type
        media_query = Q(**{f"{media_type}__isnull": False})

        # Add user filter if specified
        if user:
            media_query &= Q(**{f"{media_type}__user": user})

        active_query |= media_query

    # Add exclusion for manual sources
    active_query &= ~Q(source=Sources.MANUAL.value)

    # Return distinct items
    return Item.objects.filter(active_query)


def filter_items_needing_events(items):
    """Filter items that need calendar events."""
    now = timezone.now()

    # Subquery for future events
    future_events = Event.objects.filter(
        item=OuterRef("pk"),
        datetime__gte=now,
    )

    # Subquery for recent comic events (within last year)
    one_year_ago = now - timezone.timedelta(days=365)
    recent_comic_events = Event.objects.filter(
        item=OuterRef("pk"),
        item__media_type=MediaTypes.COMIC.value,
        datetime__gte=one_year_ago,
    ).order_by("-datetime")

    # Apply filters to identify items needing events
    return items.annotate(
        event_count=Count("event"),
        latest_comic_event=Subquery(recent_comic_events.values("datetime")[:1]),
    ).filter(
        Q(Exists(future_events))  # has future events
        | Q(event__isnull=True)  # no events
        | (
            Q(media_type=MediaTypes.COMIC.value) & Q(latest_comic_event__isnull=False)
        ),  # comics with recent events
    )


def replace_seasons_with_tv_shows(items):
    """Replace season items with their parent TV shows."""
    # Identify season items
    season_items = items.filter(media_type=MediaTypes.SEASON.value)

    if not season_items.exists():
        return items

    # Get media IDs from seasons
    season_media_ids = season_items.values_list("media_id", flat=True).distinct()

    # Find corresponding TV shows
    tv_items = Item.objects.filter(
        media_id__in=season_media_ids,
        media_type=MediaTypes.TV.value,
        source=Sources.TMDB.value,
    )

    # Get all non-season items
    non_season_items = items.exclude(media_type=MediaTypes.SEASON.value)

    # Combine non-season items with TV shows
    return non_season_items | tv_items


def process_anime_bulk(items, events_bulk):
    """Process multiple anime items and add events to the event list."""
    if not items:
        return

    anime_data = get_anime_schedule_bulk([item.media_id for item in items])

    for item in items:
        # it may not have the media_id if no matching anime was found
        episodes = anime_data.get(item.media_id)

        if episodes:
            for episode in episodes:
                episode_datetime = datetime.fromtimestamp(
                    episode["airingAt"],
                    tz=ZoneInfo("UTC"),
                )
                events_bulk.append(
                    Event(
                        item=item,
                        content_number=episode["episode"],
                        datetime=episode_datetime,
                    ),
                )


def get_anime_schedule_bulk(media_ids):
    """Get the airing schedule for multiple anime items from AniList API."""
    all_data = {}
    page = 1
    url = "https://graphql.anilist.co"
    query = """
    query ($ids: [Int], $page: Int) {
      Page(page: $page) {
        pageInfo {
          hasNextPage
        }
        media(idMal_in: $ids, type: ANIME) {
          idMal
          endDate {
            year
            month
            day
          }
          episodes
          airingSchedule {
            nodes {
              episode
              airingAt
            }
          }
        }
      }
    }
    """

    while True:
        variables = {"ids": media_ids, "page": page}
        response = services.api_request(
            "ANILIST",
            "POST",
            url,
            params={"query": query, "variables": variables},
        )

        for media in response["data"]["Page"]["media"]:
            airing_schedule = media["airingSchedule"]["nodes"]
            total_episodes = media["episodes"]
            mal_id = str(media["idMal"])

            # First check if we know the total episode count
            if total_episodes:
                if airing_schedule:
                    # Filter out episodes beyond the total count
                    original_length = len(airing_schedule)
                    airing_schedule = [
                        episode
                        for episode in airing_schedule
                        if episode["episode"] <= total_episodes
                    ]

                    # Log if any filtering occurred
                    if original_length > len(airing_schedule):
                        logger.info(
                            "Filtered episodes for MAL ID %s - keep only %s episodes",
                            mal_id,
                            total_episodes,
                        )

                # Add final episode if schedule is missing or incomplete
                if (
                    not airing_schedule
                    or airing_schedule[-1]["episode"] < total_episodes
                ):
                    end_date_timestamp = anilist_date_parser(media["endDate"])
                    if end_date_timestamp:
                        airing_schedule.append(
                            {"episode": total_episodes, "airingAt": end_date_timestamp},
                        )

            # Store the processed schedule
            all_data[mal_id] = airing_schedule

        if not response["data"]["Page"]["pageInfo"]["hasNextPage"]:
            break
        page += 1

    return all_data


def process_tv(tv_item, events_bulk):
    """Process TV item and create events for all seasons and episodes.

    Only processes:
    1. Seasons with no events
    2. Currently airing seasons (identified by next_episode_season)
    """
    logger.info("Processing TV show: %s", tv_item)

    try:
        # Get TV metadata and identify seasons to process
        seasons_to_process = get_seasons_to_process(tv_item)

        if not seasons_to_process:
            return

        # Fetch and process season data
        process_tv_seasons(tv_item, seasons_to_process, events_bulk)

    except requests.exceptions.HTTPError as err:
        if err.response.status_code == requests.codes.not_found:
            logger.warning(
                "Failed to fetch metadata for TV show %s - %s",
                tv_item,
                err.response.json(),
            )
        else:
            raise
    except Exception:
        logger.exception("Error processing TV show %s", tv_item)


def get_seasons_to_process(tv_item):
    """Identify which seasons of a TV show need to be processed."""
    tv_metadata = tmdb.tv(tv_item.media_id)

    if not tv_metadata.get("related", {}).get("seasons"):
        logger.warning("No seasons found for TV show: %s", tv_item)
        return []

    # Get all season numbers
    season_numbers = [
        season["season_number"]
        for season in tv_metadata["related"]["seasons"]
        if season["season_number"] > 0
    ]

    if not season_numbers:
        logger.warning("No valid seasons found for TV show: %s", tv_item)
        return []

    current_season = tv_metadata.get("next_episode_season")

    # Get existing events for this TV show's seasons
    existing_season_events = Event.objects.filter(
        item__media_id=tv_item.media_id,
        item__source=tv_item.source,
        item__media_type=MediaTypes.SEASON.value,
    ).select_related("item")

    # Create a set of seasons that already have events
    seasons_with_events = {event.item.season_number for event in existing_season_events}

    # Identify seasons to process:
    # 1. Seasons with no events
    # 2. Currently airing season
    seasons_to_process = []

    for season_num in season_numbers:
        if season_num not in seasons_with_events:
            # No events for this season, process it
            seasons_to_process.append(season_num)
        elif current_season and season_num == current_season:
            # Currently airing season, process it
            seasons_to_process.append(season_num)

    if not seasons_to_process:
        logger.info("%s - No seasons need processing", tv_item)
        return []

    logger.info(
        "%s - Processing %d seasons (current season: %s)",
        tv_item,
        len(seasons_to_process),
        current_season,
    )

    return seasons_to_process


def process_tv_seasons(tv_item, seasons_to_process, events_bulk):
    """Process specific seasons of a TV show."""
    # Fetch detailed data for seasons to process
    process_seasons_data = tmdb.tv_with_seasons(
        tv_item.media_id,
        seasons_to_process,
    )

    # Process each season that needs processing
    for season_number in seasons_to_process:
        season_key = f"season/{season_number}"
        if season_key not in process_seasons_data:
            logger.warning(
                "Season %s data not found for %s",
                season_number,
                tv_item,
            )
            continue

        season_metadata = process_seasons_data[season_key]

        # Get or create season item
        season_item, _ = Item.objects.get_or_create(
            media_id=tv_item.media_id,
            source=tv_item.source,
            media_type=MediaTypes.SEASON.value,
            season_number=season_number,
            defaults={
                "title": tv_item.title,
                "image": season_metadata["image"],
            },
        )

        # Process episodes for this season
        process_season_episodes(season_item, season_metadata, events_bulk)


def process_season_episodes(item, metadata, events_bulk):
    """Process episodes for a season and add them to events_bulk."""
    # Get TVMaze episode data if available
    tvmaze_map = {}
    if metadata.get("tvdb_id"):
        logger.info(
            "%s - TVDB ID found, fetching TVMaze episode data",
            item,
        )
        tvmaze_map = get_tvmaze_episode_map(metadata["tvdb_id"])
    else:
        logger.warning(
            "%s - No TVDB ID found, skipping TVMaze episode data",
            item,
        )

    # Skip if no episodes
    if not metadata.get("episodes"):
        logger.warning("%s - No episodes found in metadata", item)
        return

    # Process each episode
    for episode in metadata["episodes"]:
        episode_number = episode["episode_number"]
        season_number = metadata["season_number"]

        episode_datetime = get_episode_datetime(
            episode,
            season_number,
            episode_number,
            tvmaze_map,
        )

        events_bulk.append(
            Event(
                item=item,
                content_number=episode_number,
                datetime=episode_datetime,
            ),
        )


def get_episode_datetime(episode, season_number, episode_number, tvmaze_map):
    """Determine the most accurate air datetime for an episode."""
    # First check if we have TVMaze data for this episode
    tvmaze_key = f"{season_number}_{episode_number}"
    tvmaze_episode = tvmaze_map.get(tvmaze_key)

    # Use TVMaze data if it has an airstamp
    if tvmaze_episode and tvmaze_episode["airstamp"]:
        return datetime.fromisoformat(tvmaze_episode["airstamp"])

    # Fall back to TMDB data (date only)
    if episode["air_date"]:
        try:
            return date_parser(episode["air_date"])
        except ValueError:
            logger.warning(
                "Invalid air date for S%sE%s from TMDB: %s",
                season_number,
                episode_number,
                episode["air_date"],
            )

    # Default values for missing/invalid dates
    return datetime.min.replace(tzinfo=ZoneInfo("UTC"))


def get_tvmaze_episode_map(tvdb_id):
    """Fetch and process episode data from TVMaze using TVDB ID with caching."""
    # Check cache first for the processed map
    cache_key = f"tvmaze_map_{tvdb_id}"
    cached_map = cache.get(cache_key)

    if cached_map:
        logger.info("%s - Using cached TVMaze episode map", tvdb_id)
        return cached_map

    # First, lookup the TVMaze ID using the TVDB ID
    lookup_url = f"https://api.tvmaze.com/lookup/shows?thetvdb={tvdb_id}"
    try:
        lookup_response = services.api_request("TVMaze", "GET", lookup_url)
    except requests.exceptions.HTTPError as err:
        if err.response.status_code == requests.codes.not_found:
            logger.warning(
                "TVMaze lookup failed for TVDB ID %s - %s",
                tvdb_id,
                err.response.text(),
            )
        else:
            logger.warning(
                "%s - TVMaze lookup error: %s",
                tvdb_id,
                err.response.text(),
            )
        lookup_response = {}

    if not lookup_response:
        logger.warning("%s - No TVMaze lookup response for TVDB ID", tvdb_id)
        return {}

    tvmaze_id = lookup_response.get("id")

    if not tvmaze_id:
        logger.warning("%s - TVMaze ID not found for TVDB ID", tvdb_id)
        return {}

    # Now fetch the show with embedded episodes
    show_url = f"https://api.tvmaze.com/shows/{tvmaze_id}?embed=episodes"

    try:
        show_response = services.api_request("TVMaze", "GET", show_url)
    except requests.exceptions.HTTPError:
        return {}

    # Process episodes into the map format we need
    tvmaze_map = {}
    episodes = show_response["_embedded"]["episodes"]

    for ep in episodes:
        season_num = ep.get("season")
        episode_num = ep.get("number")
        if season_num is not None and episode_num is not None:
            key = f"{season_num}_{episode_num}"
            value = {"airstamp": ep.get("airstamp"), "airtime": ep.get("airtime")}
            tvmaze_map[key] = value

    # Cache the processed map for 24 hours
    cache.set(cache_key, tvmaze_map, timeout=86400)
    logger.info(
        "%s - Cached TVMaze episode map with %d entries",
        tvdb_id,
        len(tvmaze_map),
    )

    return tvmaze_map


def process_comic(item, events_bulk):
    """Process comic item and add events to the event list."""
    logger.info("Fetching releases for %s", item)
    try:
        metadata = services.get_media_metadata(
            item.media_type,
            item.media_id,
            item.source,
        )
    except requests.exceptions.HTTPError as err:
        # happens for niche media in which the mappings during import are incorrect
        if err.response.status_code == requests.codes.not_found:
            logger.warning(
                "Failed to fetch metadata for %s - %s",
                item,
                err.response.json(),
            )
            return
        raise

    # get latest event
    latest_event = Event.objects.filter(item=item).order_by("-datetime").first()
    last_issue_event_number = latest_event.content_number if latest_event else 0
    last_published_issue_number = metadata["max_progress"]
    if last_issue_event_number == last_published_issue_number:
        return

    # add latest issue
    try:
        issue_metadata = comicvine.issue(metadata["last_issue_id"])
    except requests.exceptions.HTTPError as err:
        logger.warning(
            "Failed to fetch issue metadata for %s - %s",
            item,
            err.response.json(),
        )
        return

    if issue_metadata["store_date"]:
        issue_datetime = date_parser(issue_metadata["store_date"])
    elif issue_metadata["cover_date"]:
        issue_datetime = date_parser(issue_metadata["cover_date"])
    else:
        return

    events_bulk.append(
        Event(
            item=item,
            content_number=last_published_issue_number,
            datetime=issue_datetime,
        ),
    )


def process_other(item, events_bulk):
    """Process other types of items and add events to the event list."""
    logger.info("Fetching releases for %s", item)
    try:
        metadata = services.get_media_metadata(
            item.media_type,
            item.media_id,
            item.source,
        )
    except requests.exceptions.HTTPError as err:
        # happens for niche media in which the mappings during import are incorrect
        if err.response.status_code == requests.codes.not_found:
            logger.warning(
                "Failed to fetch metadata for %s - %s",
                item,
                err.response.json(),
            )
            return
        raise

    date_key = media_type_config.get_date_key(item.media_type)

    if date_key in metadata["details"] and metadata["details"][date_key]:
        try:
            content_datetime = date_parser(metadata["details"][date_key])
        except ValueError:
            pass
        else:
            content_number = (
                None
                if item.media_type == MediaTypes.MOVIE.value
                else metadata["max_progress"]
            )
            events_bulk.append(
                Event(
                    item=item,
                    content_number=content_number,
                    datetime=content_datetime,
                ),
            )

    elif item.source == Sources.MANGAUPDATES.value and metadata["max_progress"]:
        # MangaUpdates doesn't have an end date, so use a placeholder
        content_datetime = datetime.min.replace(tzinfo=ZoneInfo("UTC"))
        events_bulk.append(
            Event(
                item=item,
                content_number=metadata["max_progress"],
                datetime=content_datetime,
            ),
        )


def date_parser(date_str):
    """Parse string in %Y-%m-%d to datetime. Raises ValueError if invalid."""
    year_only_parts = 1
    year_month_parts = 2
    default_month_day = "-01-01"
    default_day = "-01"
    # Preprocess the date string
    parts = date_str.split("-")
    if len(parts) == year_only_parts:
        date_str += default_month_day
    elif len(parts) == year_month_parts:
        # Year and month are provided, append "-01"
        date_str += default_day

    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=ZoneInfo("UTC"))
    # Set to max time and add UTC timezone
    return dt.replace(
        hour=SentinelDatetime.HOUR,
        minute=SentinelDatetime.MINUTE,
        second=SentinelDatetime.SECOND,
        microsecond=SentinelDatetime.MICROSECOND,
        tzinfo=ZoneInfo("UTC"),
    )


def anilist_date_parser(start_date):
    """Parse the start date from AniList to a timestamp."""
    if not start_date["year"]:
        return None

    month = start_date["month"] or 1
    day = start_date["day"] or 1

    # Create date with max time
    dt = datetime(
        start_date["year"],
        month,
        day,
        hour=SentinelDatetime.HOUR,
        minute=SentinelDatetime.MINUTE,
        second=SentinelDatetime.SECOND,
        microsecond=SentinelDatetime.MICROSECOND,
        tzinfo=ZoneInfo("UTC"),
    )

    return dt.timestamp()
