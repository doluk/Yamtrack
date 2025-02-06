import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from celery import shared_task
from django.conf import settings
from django.db.models import Q

from app.models import Item
from app.providers import services, tmdb
from events.models import Event

logger = logging.getLogger(__name__)

DEFAULT_MONTH_DAY = "-01-01"
DEFAULT_DAY = "-01"


@shared_task(name="Reload calendar")
def reload_calendar(user=None, items_to_process=None):  # used for metadata
    """Refresh the calendar with latest dates for all users."""
    if not items_to_process:
        items_to_process = Event.objects.get_items_to_process()

    events_bulk = []
    anime_to_process = []

    for item in items_to_process:
        # anime can later be processed in bulk
        if item.media_type == "anime":
            anime_to_process.append(item)
        else:
            process_item(item, events_bulk)

    # process anime items in bulk
    process_anime_bulk(anime_to_process, events_bulk)
    for event in events_bulk:
        Event.objects.update_or_create(
            item=event.item,
            episode_number=event.episode_number,
            defaults={"date": event.date},
        )

    if user:
        reloaded_items = get_user_reloaded(events_bulk, user)
    else:
        reloaded_items = {event.item for event in events_bulk}

    reloaded_count = len(reloaded_items)
    result_msg = "\n".join(
        f"{item} ({item.media_type_readable})" for item in reloaded_items
    )

    if reloaded_count > 0:
        return f"""The following items have been loaded to the calendar:\n
                    {result_msg}"""
    return "There have been no changes in the calendar"


def process_item(item, events_bulk):
    """Process each item and add events to the event list."""
    try:
        if item.media_type == "season":
            tv_with_seasons_metadata = tmdb.tv_with_seasons(
                item.media_id,
                [item.season_number],
            )
            metadata = tv_with_seasons_metadata[f"season/{item.season_number}"]
            process_season(item, metadata, events_bulk)
        else:
            metadata = services.get_media_metadata(
                item.media_type,
                item.media_id,
                item.source,
            )
            process_other(item, metadata, events_bulk)
    except requests.exceptions.HTTPError as err:
        # happens for niche media in which the mappings during import are incorrect
        if err.response.status_code == requests.codes.not_found:
            msg = f"{item} ({item.media_id}) not found on {item.source}. Deleting it."
            logger.warning(msg)
            item.delete()
        else:
            raise


def process_anime_bulk(items, events_bulk):
    """Process multiple anime items and add events to the event list."""
    anime_data = get_anime_schedule_bulk([item.media_id for item in items])

    for item in items:
        # it may not have the media_id if no matching anime was found
        episodes = anime_data.get(item.media_id)

        if episodes:
            for episode in episodes:
                air_date = datetime.fromtimestamp(
                    episode["airingAt"],
                    tz=ZoneInfo("UTC"),
                )
                local_air_date = air_date.astimezone(settings.TZ)
                events_bulk.append(
                    Event(
                        item=item,
                        episode_number=episode["episode"],
                        date=local_air_date,
                    ),
                )


def get_anime_schedule_bulk(media_ids):
    """Get the airing schedule for multiple anime items from AniList API."""
    all_data = {}
    page = 1

    while True:
        query = """
        query ($ids: [Int], $page: Int) {
          Page(page: $page) {
            pageInfo {
              hasNextPage
            }
            media(idMal_in: $ids, type: ANIME) {
              idMal
              startDate {
                year
                month
                day
              }
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
        variables = {"ids": media_ids, "page": page}
        url = "https://graphql.anilist.co"
        response = services.api_request(
            "ANILIST",
            "POST",
            url,
            params={"query": query, "variables": variables},
        )

        media_list = response["data"]["Page"]["media"]

        for media in media_list:
            airing_schedule = media["airingSchedule"]["nodes"]

            # if no airing schedule is available, use the start date
            if not airing_schedule:
                timestamp = anilist_date_parser(media["startDate"])
                if timestamp:
                    airing_schedule = [
                        {
                            "episode": 1,
                            "airingAt": timestamp,
                        },
                    ]
                else:
                    airing_schedule = []

            all_data[str(media["idMal"])] = airing_schedule

        if not response["data"]["Page"]["pageInfo"]["hasNextPage"]:
            break

        page += 1

    return all_data


def process_season(item, metadata, events_bulk):
    """Process season item and add events to the event list."""
    for episode in reversed(metadata["episodes"]):
        if episode["air_date"]:
            try:
                air_date = date_parser(episode["air_date"])
                events_bulk.append(
                    Event(
                        item=item,
                        episode_number=episode["episode_number"],
                        date=air_date,
                    ),
                )
            except ValueError:
                pass


def process_other(item, metadata, events_bulk):
    """Process other types of items and add events to the event list."""
    # it will have either of these keys
    date_keys = ["start_date", "release_date", "first_air_date", "publish_date"]
    for date_key in date_keys:
        if date_key in metadata["details"] and metadata["details"][date_key]:
            try:
                air_date = date_parser(metadata["details"][date_key])
                events_bulk.append(Event(item=item, date=air_date))
            except ValueError:
                pass


def date_parser(date_str):
    """Parse string in %Y-%m-%d to datetime. Raises ValueError if invalid."""
    year_only_parts = 1
    year_month_parts = 2
    # Preprocess the date string
    parts = date_str.split("-")
    if len(parts) == year_only_parts:
        date_str += DEFAULT_MONTH_DAY
    elif len(parts) == year_month_parts:
        # Year and month are provided, append "-01"
        date_str += DEFAULT_DAY

    # Parse the date string
    return datetime.strptime(date_str, "%Y-%m-%d").replace(
        tzinfo=ZoneInfo("UTC"),
    )


def anilist_date_parser(start_date):
    """Parse the start date from AniList to a timestamp."""
    if not start_date["year"]:
        return None

    month = start_date["month"] or 1
    day = start_date["day"] or 1
    return datetime(start_date["year"], month, day, tzinfo=ZoneInfo("UTC")).timestamp()


def get_user_reloaded(reloaded_events, user):
    """Get the items that have been reloaded for the user."""
    event_item_ids = {event.item_id for event in reloaded_events}

    media_type_groups = {}
    for item_id, media_type in Item.objects.filter(
        id__in=event_item_ids,
    ).values_list("id", "media_type"):
        media_type_groups.setdefault(media_type, set()).add(item_id)

    q_filters = Q()
    for media_type, item_ids in media_type_groups.items():
        q_filters |= Q(
            id__in=item_ids,
            media_type=media_type,
            **{f"{media_type}__user": user},
        )

    return Item.objects.filter(q_filters).distinct()
