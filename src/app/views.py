import logging

from django.apps import apps
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from app import database, helpers
from app.forms import FilterForm, ManualItemForm, get_form_class
from app.models import BasicMedia, Episode, Item, Media, Season
from app.providers import manual, services, tmdb

logger = logging.getLogger(__name__)


@require_GET
def home(request):
    """Home page with media items in progress and repeating."""
    list_by_type = database.get_in_progress(request.user)
    context = {"list_by_type": list_by_type}
    return render(request, "app/home.html", context)


@require_POST
def progress_edit(request):
    """Increase or decrease the progress of a media item from home page."""
    item = Item.objects.get(id=request.POST["item"])
    media_type = item.media_type
    operation = request.POST["operation"]

    media = database.get_media(media_type, item, request.user)

    if media:
        if operation == "increase":
            media.increase_progress()
        elif operation == "decrease":
            media.decrease_progress()

        response = media.progress_response()
        return render(
            request,
            "app/components/progress_changer.html",
            {"media": response, "media_type": media_type},
        )

    messages.error(
        request,
        "Media item was deleted before trying to change progress",
    )

    response = HttpResponse()
    response["HX-Redirect"] = reverse("home")
    return response


@require_GET
def media_list(request, media_type):
    """Return the media list page."""
    layout_user = request.user.get_layout(media_type)

    if request.GET:
        layout_request = request.GET.get("layout", layout_user)
        filter_form = FilterForm(request.GET, layout=layout_request)
        if layout_request != layout_user:
            if filter_form.is_valid():
                request.user.set_layout(media_type, layout_request)
                layout_user = layout_request
            else:
                logger.error(filter_form.errors.as_json())
    else: # first time access
        filter_form = FilterForm(layout=layout_user)

    status_filter = request.GET.get("status", "all")
    sort_filter = request.GET.get("sort", "score")
    search_query = request.GET.get("search", "")
    page = request.GET.get("page", 1)

    media_queryset = database.get_media_list(
        user=request.user,
        media_type=media_type,
        status_filter=[status_filter.capitalize()],
        sort_filter=sort_filter,
        search=search_query,
    )

    items_per_page = 25
    paginator = Paginator(media_queryset, items_per_page)
    media_page = paginator.get_page(page)

    context = {
        "media_type": media_type,
        "media_list": media_page,
        "current_page": page,
        "user_layout": layout_user,
        "first_request": not request.GET,
    }

    if request.headers.get("HX-Request"):
        if request.GET.get("layout") == "grid":
            template_name = "app/components/media_grid_items.html"
        else:
            template_name = "app/components/media_table_items.html"
    else:
        template_name = "app/media_list.html"
        context["layout"] = layout_user

    return render(request, template_name, context)


@require_GET
def media_search(request):
    """Return the media search page."""
    media_type = request.GET["media_type"]
    query = request.GET["q"]
    request.user.set_last_search_type(media_type)

    # only receives source when searching with secondary source
    source = request.GET.get("source")

    query_list = services.search(media_type, query, source)

    context = {"query_list": query_list, "source": source}

    return render(request, "app/search.html", context)


@require_GET
def media_details(request, source, media_type, media_id, title):  # noqa: ARG001 title for URL
    """Return the details page for a media item."""
    media_metadata = services.get_media_metadata(media_type, media_id, source)

    context = {"media": media_metadata, "media_type": media_type}
    return render(request, "app/media_details.html", context)


@require_GET
def season_details(request, source, media_id, title, season_number):  # noqa: ARG001 For URL
    """Return the details page for a season."""
    tv_with_seasons_metadata = services.get_media_metadata(
        "tv_with_seasons",
        media_id,
        source,
        [season_number],
    )
    season_metadata = tv_with_seasons_metadata[f"season/{season_number}"]
    episodes_in_db = Episode.objects.filter(
        item__media_id=media_id,
        item__source=source,
        item__season_number=season_number,
        related_season__user=request.user,
    ).values("item__episode_number", "end_date", "repeats")

    if source == "manual":
        season_metadata["episodes"] = manual.process_episodes(
            season_metadata,
            episodes_in_db,
        )
    else:
        season_metadata["episodes"] = tmdb.process_episodes(
            season_metadata,
            episodes_in_db,
        )

    context = {
        "season": season_metadata,
        "tv": tv_with_seasons_metadata,
        "media_type": "season",
    }
    return render(request, "app/season_details.html", context)


@require_GET
def track_modal(
    request,
    source,
    media_type,
    media_id,
    season_number=None,
):
    """Return the tracking form for a media item."""
    metadata = services.get_media_metadata(
        media_type,
        media_id,
        source,
        [season_number],
    )

    item, _ = Item.objects.get_or_create(
        media_id=media_id,
        source=source,
        media_type=media_type,
        season_number=season_number,
        defaults={
            "title": metadata["title"],
            "image": metadata["image"],
        },
    )

    media = database.get_media(media_type, item, request.user)

    initial_data = {
        "item": item,
    }

    if media_type == "game" and media:
        initial_data["progress"] = helpers.minutes_to_hhmm(media.progress)

    form = get_form_class(media_type)(instance=media, initial=initial_data)

    title = metadata["title"]
    if season_number:
        title = f"{title} S{season_number}"

    form_id = f"form-{item.id}"
    form.helper.form_id = form_id

    return render(
        request,
        "app/components/fill_track.html",
        {
            "title": title,
            "form_id": form_id,
            "form": form,
            "media": media,
            "return_url": request.GET["return_url"],
        },
    )


@require_POST
def media_save(request):
    """Save or update media data to the database."""
    item = Item.objects.get(id=request.POST["item"])
    media_type = item.media_type

    instance = database.get_media(media_type, item, request.user)

    if not instance:
        model = apps.get_model(app_label="app", model_name=media_type)
        instance = model(item=item, user=request.user)

    # Validate the form and save the instance if it's valid
    form_class = get_form_class(media_type)
    form = form_class(request.POST, instance=instance)
    if form.is_valid():
        form.save()
        logger.info("%s saved successfully.", form.instance)
    else:
        logger.error(form.errors.as_json())
        messages.error(
            request,
            # Get the first error message from the form
            next(iter(form.errors.get_json_data().values()))[0]["message"],
        )

    return helpers.redirect_back(request)


@require_POST
def media_delete(request):
    """Delete media data from the database."""
    item = Item.objects.get(id=request.POST["item"])
    media_type = item.media_type

    media = database.get_media(media_type, item, request.user)
    if media:
        media.delete()
        logger.info("%s deleted successfully.", media)
    else:
        logger.warning("The %s was already deleted before.", media_type)

    return helpers.redirect_back(request)


@require_POST
def episode_handler(request):
    """Handle the creation, deletion, and updating of episodes for a season."""
    media_id = request.POST["media_id"]
    season_number = request.POST["season_number"]
    episode_number = request.POST["episode_number"]
    source = request.POST["source"]

    try:
        related_season = Season.objects.get(
            item__media_id=media_id,
            item__source=source,
            item__season_number=season_number,
            item__episode_number=None,
            user=request.user,
        )
    except Season.DoesNotExist:
        tv_with_seasons_metadata = services.get_media_metadata(
            "tv_with_seasons",
            media_id,
            source,
            [season_number],
        )
        season_metadata = tv_with_seasons_metadata[f"season/{season_number}"]

        item, _ = Item.objects.get_or_create(
            media_id=media_id,
            source="tmdb",
            media_type="season",
            season_number=season_number,
            defaults={
                "title": tv_with_seasons_metadata["title"],
                "image": season_metadata["image"],
            },
        )
        related_season = Season(
            item=item,
            user=request.user,
            score=None,
            status=Media.Status.IN_PROGRESS.value,
            notes="",
        )

        related_season.save()
        logger.info("%s did not exist, it was created successfully.", related_season)

    if "unwatch" in request.POST:
        related_season.unwatch(episode_number)

    else:
        if "release" in request.POST:
            end_date = request.POST["release"]
        else:
            # set watch date from form
            end_date = request.POST["date"]
        related_season.watch(episode_number, end_date)

    return helpers.redirect_back(request)


@require_http_methods(["GET", "POST"])
def create_item(request):
    """Return the form for manually adding media items."""
    if request.method == "POST":
        form = ManualItemForm(request.POST, user=request.user)
        if form.is_valid():
            try:
                item = form.save()
            except IntegrityError:
                msg = "This item already exists in the database."
                messages.error(request, msg)
                logger.warning(msg)
                return redirect("create_item")

            updated_request = request.POST.copy()
            updated_request.update({"item": item.id})
            media_form = get_form_class(item.media_type)(updated_request)

            if media_form.is_valid():
                media_form.instance.user = request.user
                if item.media_type == "season":
                    media_form.instance.related_tv = form.cleaned_data["parent_tv"]
                elif item.media_type == "episode":
                    media_form.instance.related_season = form.cleaned_data[
                        "parent_season"
                    ]
                media_form.save()
                msg = f"{item} added successfully."
                messages.success(request, msg)
                logger.info(msg)

            return redirect("create_item")

    form = ManualItemForm(user=request.user)
    context = {"form": form, "media_form": get_form_class(form["media_type"].value())}

    return render(request, "app/create_item.html", context)


@require_GET
def create_media(request):
    """Return the form for manually adding media items."""
    media_type = request.GET.get("media_type")
    context = {"form": get_form_class(media_type)}
    return render(request, "app/components/create_media.html", context)


@require_GET
def history_modal(
    request,
    source,
    media_type,
    media_id,
    season_number=None,
    episode_number=None,
):
    """Return the history page for a media item."""
    metadata = services.get_media_metadata(
        media_type,
        media_id,
        source,
        [season_number],
        episode_number,
    )

    item, _ = Item.objects.get_or_create(
        media_id=media_id,
        source=source,
        media_type=media_type,
        season_number=season_number,
        episode_number=episode_number,
        defaults={
            "title": metadata["title"],
            "image": metadata["image"],
        },
    )

    media = database.get_media(media_type, item, request.user)
    changes = []
    if media:
        history = media.history.all()
        if history is not None:
            last = history.first()
            for _ in range(history.count()):
                new_record, old_record = last, last.prev_record
                if old_record is not None:
                    delta = new_record.diff_against(old_record)
                    changes.append(delta)
                    last = old_record
                else:
                    # If there is no previous record, it's a creation entry
                    history_model = apps.get_model(
                        app_label="app",
                        model_name=f"historical{media_type}",
                    )
                    creation_changes = [
                        {
                            "field": field.verbose_name,
                            "new": getattr(new_record, field.attname),
                        }
                        for field in history_model._meta.get_fields()  # noqa: SLF001
                        if getattr(new_record, field.attname)  # not None/0/empty
                        and not field.name.startswith("history")
                        and field.name != "id"
                    ]
                    changes.append(
                        {
                            "new_record": new_record,
                            "changes": creation_changes,
                        },
                    )

    return render(
        request,
        "app/components/fill_history.html",
        {
            "media_type": media_type,
            "changes": changes,
            "return_url": request.GET["return_url"],
        },
    )


@require_POST
def history_delete(request):
    """Delete a history record for a media item."""
    history_id = request.POST["history_id"]
    media_type = request.POST["media_type"]

    model_name = f"historical{media_type}"

    history = apps.get_model(app_label="app", model_name=model_name).objects.get(
        history_id=history_id,
    )

    if history.history_user_id == request.user.id:
        history.delete()
        logger.info("History record deleted successfully.")
    else:
        logger.warning("User does not have permission to delete this history record.")

    return helpers.redirect_back(request)


@require_GET
def statistics(request):
    """Return the statistics page."""
    # Set default date range to last year
    timeformat = "%Y-%m-%d"
    today = timezone.now().date()
    one_year_ago = today.replace(year=today.year - 1)

    start_date_str = request.GET.get("start-date", one_year_ago.strftime(timeformat))
    if start_date_str == "":
        start_date_str = one_year_ago.strftime(timeformat)
    end_date_str = request.GET.get("end-date", today.strftime(timeformat))
    if end_date_str == "":
        end_date_str = today.strftime(timeformat)

    # Convert strings directly to datetime.date objects
    start_date = timezone.datetime.strptime(start_date_str, timeformat).date()
    end_date = timezone.datetime.strptime(end_date_str, timeformat).date()

    activity_data = database.get_activity_data(
        request.user,
        start_date,
        end_date,
    )

    user_media, media_count = BasicMedia.objects.get_user_media(
        request.user,
        start_date,
        end_date,
    )

    score_distribution = BasicMedia.objects.get_score_distribution(user_media)
    status_distribution = BasicMedia.objects.get_status_distribution(user_media)
    timeline = BasicMedia.objects.get_timeline(user_media)
    context = {
        "start_date": start_date,
        "end_date": end_date,
        "range": request.GET.get("range", "last12Months"),
        "media_count": media_count,
        "activity_data": activity_data,
        "score_distribution": score_distribution,
        "status_distribution": status_distribution,
        "timeline": timeline,
    }

    return render(request, "app/statistics.html", context)
