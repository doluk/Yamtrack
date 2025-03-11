import logging

from django.apps import apps
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, F, OuterRef, Q, Subquery
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_POST

from app import helpers
from app.models import Item, MediaTypes
from app.providers import services
from lists.forms import CustomListForm
from lists.models import CustomList, CustomListItem
from users.models import ListSortChoices

logger = logging.getLogger(__name__)


@require_GET
def lists(request):
    """Return the custom list page."""
    # Get parameters from request
    sort_by = request.GET.get("sort") or request.user.lists_sort
    search_query = request.GET.get("q", "")
    page = request.GET.get("page", 1)

    if sort_by != request.user.lists_sort:
        request.user.lists_sort = sort_by
        request.user.save(update_fields=["lists_sort"])

    custom_lists = CustomList.objects.get_user_lists(request.user)

    if search_query:
        custom_lists = custom_lists.filter(
            Q(name__icontains=search_query) | Q(description__icontains=search_query),
        )

    if sort_by == "name":
        custom_lists = custom_lists.order_by("name")
    elif sort_by == "items_count":
        custom_lists = custom_lists.annotate(
            items_count=Count("items", distinct=True),
        ).order_by("-items_count")
    elif sort_by == "newest_first":
        custom_lists = custom_lists.order_by("-id")
    else:  # last_item_added is the default
        # Get the latest update date for each list
        custom_lists = custom_lists.annotate(
            latest_update=Subquery(
                CustomListItem.objects.filter(
                    custom_list=OuterRef("pk"),
                )
                .order_by("-date_added")
                .values("date_added")[:1],
            ),
        ).order_by("-latest_update", "name")

    items_per_page = 20
    paginator = Paginator(custom_lists, items_per_page)
    lists_page = paginator.get_page(page)

    # Create a form for each list
    # needs unique id for django-select2
    for i, custom_list in enumerate(lists_page, start=1):
        custom_list.form = CustomListForm(
            instance=custom_list,
            auto_id=f"id_{i}_%s",
        )

    if request.headers.get("HX-Request"):
        return render(
            request,
            "lists/components/list_grid.html",
            {
                "custom_lists": lists_page,
            },
        )

    create_list_form = CustomListForm()

    return render(
        request,
        "lists/custom_lists.html",
        {
            "custom_lists": lists_page,
            "form": create_list_form,
            "current_sort": sort_by,
            "sort_choices": ListSortChoices.choices,
        },
    )


@require_GET
def list_detail(request, list_id):
    """Return the detail page of a custom list."""
    custom_list = get_object_or_404(
        CustomList.objects.select_related("owner").prefetch_related("collaborators"),
        id=list_id,
    )

    if not custom_list.user_can_view(request.user):
        msg = "List not found"
        raise Http404(msg)

    sort_by = request.GET.get("sort", "date_added")
    media_type = request.GET.get("type", "all")
    page = request.GET.get("page", 1)
    search_query = request.GET.get("q", "")

    # Apply filters and sorting
    items = custom_list.items.all()
    if search_query:
        items = items.filter(title__icontains=search_query)
    if media_type != "all":
        items = items.filter(media_type=media_type)

    # Apply sorting
    sort_options = {
        "date_added": "-customlistitem__date_added",
        "title": ("title", "season_number", "episode_number"),
        "media_type": "media_type",
    }
    sort_field = sort_options.get(sort_by, "-customlistitem__date_added")

    if isinstance(sort_field, tuple):
        # Create order expressions for tuple-based sorting
        items = items.order_by(
            *[
                F(field).asc(nulls_last=True)
                if field in ["season_number", "episode_number"]
                else field
                for field in sort_field
            ],
        )
    else:
        items = items.order_by(sort_field)

    # Paginate and prepare items
    paginator = Paginator(items, 16)
    items_page = paginator.get_page(page)

    # Get media objects for the current page
    item_ids = [item.id for item in items_page]
    media_by_item_id = {}

    # Get media objects by type
    for media_type in {item.media_type for item in items_page}:
        model = apps.get_model("app", media_type)
        filter_kwargs = {"item_id__in": item_ids}

        # Handle episode type differently
        if media_type == "episode":
            filter_kwargs["related_season__user"] = request.user
        else:
            filter_kwargs["user"] = request.user

        entries = model.objects.filter(**filter_kwargs).select_related("item")

        for entry in entries:
            media_by_item_id[entry.item_id] = entry

    # Add media to each item
    for item in items_page:
        item.media = media_by_item_id.get(item.id)

    # Prepare context
    context = {
        "custom_list": custom_list,
        "items": items_page,
        "has_next": items_page.has_next(),
        "next_page_number": items_page.next_page_number()
        if items_page.has_next()
        else None,
    }

    # For full page render, add additional context
    if not request.headers.get("HX-Request"):
        context.update(
            {
                "form": CustomListForm(instance=custom_list),
                "media_types": MediaTypes.values,
                "items_count": paginator.count,
                "collaborators_count": custom_list.collaborators.count() + 1,
            },
        )
        return render(request, "lists/list_detail.html", context)

    # For HTMX request
    return render(request, "lists/components/media_grid.html", context)


@require_POST
def create(request):
    """Create a new custom list."""
    form = CustomListForm(request.POST)
    if form.is_valid():
        custom_list = form.save(commit=False)
        custom_list.owner = request.user
        custom_list.save()
        form.save_m2m()
        logger.info("%s list created successfully.", custom_list)
    else:
        logger.error(form.errors.as_json())
        helpers.form_error_messages(form, request)
    return helpers.redirect_back(request)


@require_POST
def edit(request):
    """Edit an existing custom list."""
    list_id = request.POST.get("list_id")
    custom_list = get_object_or_404(CustomList, id=list_id)
    if custom_list.user_can_edit(request.user):
        form = CustomListForm(request.POST, instance=custom_list)
        if form.is_valid():
            form.save()
            logger.info("%s list edited successfully.", custom_list)
    else:
        messages.error(request, "You do not have permission to edit this list.")
    return helpers.redirect_back(request)


@require_POST
def delete(request):
    """Delete a custom list."""
    list_id = request.POST.get("list_id")
    custom_list = get_object_or_404(CustomList, id=list_id)
    if custom_list.user_can_delete(request.user):
        custom_list.delete()
        logger.info("%s list deleted successfully.", custom_list)
    else:
        messages.error(request, "You do not have permission to delete this list.")
    return helpers.redirect_back(request)


@require_GET
def lists_modal(
    request,
    source,
    media_type,
    media_id,
    season_number=None,
    episode_number=None,
):
    """Return the modal showing all custom lists and allowing to add to them."""
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

    custom_lists = CustomList.objects.get_user_lists_with_item(request.user, item)

    return render(
        request,
        "lists/components/fill_lists.html",
        {"item": item, "custom_lists": custom_lists},
    )


@require_POST
def list_item_toggle(request):
    """Add or remove an item from a custom list."""
    item_id = request.POST["item_id"]
    custom_list_id = request.POST["custom_list_id"]

    item = get_object_or_404(Item, id=item_id)
    custom_list = get_object_or_404(
        CustomList.objects.filter(
            Q(owner=request.user) | Q(collaborators=request.user),
            id=custom_list_id,
        ).distinct(),  # To prevent duplicates, when user is owner and collaborator
    )

    if custom_list.items.filter(id=item.id).exists():
        custom_list.items.remove(item)
        logger.info("%s removed from %s.", item, custom_list)
        has_item = False
    else:
        custom_list.items.add(item)
        logger.info("%s added to %s.", item, custom_list)
        has_item = True

    return render(
        request,
        "lists/components/list_item_button.html",
        {"custom_list": custom_list, "item": item, "has_item": has_item},
    )
