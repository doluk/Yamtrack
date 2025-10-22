import logging
from urllib.parse import parse_qsl, urlencode, urlparse
from uuid import uuid4

import boto3
from botocore.exceptions import ClientError
from django.conf import settings
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from django.utils.encoding import iri_to_uri
from django.utils.http import url_has_allowed_host_and_scheme

logger = logging.getLogger(__name__)


def minutes_to_hhmm(total_minutes):
    """Convert total minutes to HH:MM format."""
    hours = int(total_minutes / 60)
    minutes = int(total_minutes % 60)
    if hours == 0:
        return f"{minutes}min"
    return f"{hours}h {minutes:02d}min"


def redirect_back(request):
    """Redirect to the previous page, removing the 'page' parameter if present."""
    if url_has_allowed_host_and_scheme(request.GET.get("next"), None):
        next_url = request.GET["next"]

        # Parse the URL
        parsed_url = urlparse(next_url)

        # Get the query parameters and remove params we don't want
        query_params = dict(parse_qsl(parsed_url.query))
        query_params.pop("page", None)
        query_params.pop("load_media_type", None)

        # Reconstruct the URL
        new_query = urlencode(query_params)
        new_parts = list(parsed_url)
        new_parts[4] = new_query  # index 4 is the query part

        # Convert back to a URL string
        clean_url = iri_to_uri(parsed_url._replace(query=new_query).geturl())

        return HttpResponseRedirect(clean_url)

    return redirect("home")


def form_error_messages(form, request):
    """Display form errors as messages."""
    for field, errors in form.errors.items():
        for error in errors:
            messages.error(
                request,
                f"{field.replace('_', ' ').title()}: {error}",
            )


def format_search_response(page, per_page, total_results, results):
    """Format the search response for pagination."""
    return {
        "page": page,
        "total_results": total_results,
        "total_pages": total_results // per_page + 1,
        "results": results,
    }


def upload_to_s3(file, bucket_name=None, region_name=None):
    """Upload a file to S3 and return the URL.

    Args:
        file: The uploaded file object
        bucket_name: Optional S3 bucket name (defaults to settings.AWS_S3_BUCKET_NAME)
        region_name: Optional S3 region (defaults to settings.AWS_S3_REGION_NAME)

    Returns:
        str: The S3 URL of the uploaded file or None if upload fails

    Raises:
        ValueError: If AWS credentials or bucket name are not configured
    """
    # Check if S3 is configured
    if not settings.AWS_ACCESS_KEY_ID or not settings.AWS_SECRET_ACCESS_KEY:
        msg = "AWS credentials are not configured"
        raise ValueError(msg)

    bucket_name = bucket_name or settings.AWS_S3_BUCKET_NAME
    if not bucket_name:
        msg = "AWS S3 bucket name is not configured"
        raise ValueError(msg)

    region_name = region_name or settings.AWS_S3_REGION_NAME

    # Generate a unique filename
    file_extension = file.name.split(".")[-1] if "." in file.name else ""
    unique_filename = f"custom-media/{uuid4()}.{file_extension}"

    # Upload to S3
    s3_client = boto3.client(
        "s3",
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=region_name,
    )

    try:
        s3_client.upload_fileobj(
            file,
            bucket_name,
            unique_filename,
            ExtraArgs={"ContentType": file.content_type},
        )

        # Generate and return the S3 URL
        return f"https://{bucket_name}.s3.{region_name}.amazonaws.com/{unique_filename}"

    except ClientError:
        # Log the error and return None
        logger.exception("Failed to upload file to S3")
        return None
