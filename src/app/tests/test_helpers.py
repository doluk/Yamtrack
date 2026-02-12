from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError
from django.http import HttpRequest
from django.test import TestCase, override_settings

from app.helpers import (
    form_error_messages,
    minutes_to_hhmm,
    redirect_back,
    upload_to_s3,
)


class HelpersTest(TestCase):
    """Test helper functions."""

    def test_minutes_to_hhmm(self):
        """Test conversion of minutes to HH:MM format."""
        # Test minutes only
        self.assertEqual(minutes_to_hhmm(30), "30min")

        # Test hours and minutes
        self.assertEqual(minutes_to_hhmm(90), "1h 30min")
        self.assertEqual(minutes_to_hhmm(125), "2h 05min")

        # Test zero
        self.assertEqual(minutes_to_hhmm(0), "0min")

    @patch("app.helpers.url_has_allowed_host_and_scheme")
    @patch("app.helpers.HttpResponseRedirect")
    @patch("app.helpers.redirect")
    def test_redirect_back_with_next(self, _, mock_http_redirect, mock_url_check):
        """Test redirect_back with a 'next' parameter."""
        mock_url_check.return_value = True
        mock_http_redirect.return_value = "redirected"

        request = MagicMock()
        request.GET = {"next": "http://example.com/path?page=2&sort=name"}

        result = redirect_back(request)

        # Check that we redirected to the URL without the page parameter
        mock_http_redirect.assert_called_once()
        redirect_url = mock_http_redirect.call_args[0][0]
        self.assertEqual(redirect_url, "http://example.com/path?sort=name")
        self.assertEqual(result, "redirected")

    @patch("app.helpers.url_has_allowed_host_and_scheme")
    @patch("app.helpers.redirect")
    def test_redirect_back_without_next(self, mock_redirect, mock_url_check):
        """Test redirect_back without a 'next' parameter."""
        mock_url_check.return_value = False
        mock_redirect.return_value = "home_redirect"

        request = MagicMock()
        request.GET = {}

        result = redirect_back(request)

        mock_redirect.assert_called_once_with("home")
        self.assertEqual(result, "home_redirect")

    @patch("app.helpers.messages")
    def test_form_error_messages(self, mock_messages):
        """Test form_error_messages function."""
        form = MagicMock()
        form.errors = {
            "title": ["This field is required."],
            "release_date": ["Enter a valid date."],
        }
        request = HttpRequest()

        form_error_messages(form, request)

        # Check that error messages were added
        self.assertEqual(mock_messages.error.call_count, 2)
        mock_messages.error.assert_any_call(request, "Title: This field is required.")
        mock_messages.error.assert_any_call(
            request,
            "Release Date: Enter a valid date.",
        )


class UploadToS3Test(TestCase):
    """Test upload_to_s3 function."""

    @override_settings(
        AWS_ACCESS_KEY_ID="test_key",
        AWS_SECRET_ACCESS_KEY="test_secret"  ,  # noqa: S106
        AWS_S3_BUCKET_NAME="test_bucket",
        AWS_S3_REGION_NAME="us-east-1",
    )
    @patch("app.helpers.boto3.client")
    def test_upload_to_s3_success(self, mock_boto_client):
        """Test successful upload to S3."""
        # Mock the S3 client
        mock_s3 = MagicMock()
        mock_boto_client.return_value = mock_s3

        # Create a mock file
        mock_file = MagicMock()
        mock_file.name = "test_image.jpg"
        mock_file.content_type = "image/jpeg"

        # Call the function
        result = upload_to_s3(mock_file)

        # Verify boto3 client was created with correct credentials
        mock_boto_client.assert_called_once_with(
            "s3",
            aws_access_key_id="test_key",
            aws_secret_access_key="test_secret"  ,  # noqa: S106
            region_name="us-east-1",
        )

        # Verify upload was called
        mock_s3.upload_fileobj.assert_called_once()

        # Verify the result is a valid S3 URL
        self.assertIsNotNone(result)
        self.assertTrue(
            result.startswith(
                "https://test_bucket.s3.us-east-1.amazonaws.com/custom-media/",
            ),
        )
        self.assertTrue(result.endswith(".jpg"))

    @override_settings(AWS_ACCESS_KEY_ID=None, AWS_SECRET_ACCESS_KEY=None)
    def test_upload_to_s3_no_credentials(self):
        """Test upload_to_s3 raises error when credentials are missing."""
        mock_file = MagicMock()
        mock_file.name = "test_image.jpg"

        with self.assertRaises(ValueError) as context:
            upload_to_s3(mock_file)

        self.assertIn("AWS credentials are not configured", str(context.exception))

    @override_settings(
        AWS_ACCESS_KEY_ID="test_key",
        AWS_SECRET_ACCESS_KEY="test_secret"  ,  # noqa: S106
        AWS_S3_BUCKET_NAME=None,
    )
    def test_upload_to_s3_no_bucket(self):
        """Test upload_to_s3 raises error when bucket name is missing."""
        mock_file = MagicMock()
        mock_file.name = "test_image.jpg"

        with self.assertRaises(ValueError) as context:
            upload_to_s3(mock_file)

        self.assertIn("AWS S3 bucket name is not configured", str(context.exception))

    @override_settings(
        AWS_ACCESS_KEY_ID="test_key",
        AWS_SECRET_ACCESS_KEY="test_secret"  ,  # noqa: S106
        AWS_S3_BUCKET_NAME="test_bucket",
        AWS_S3_REGION_NAME="us-east-1",
    )
    @patch("app.helpers.boto3.client")
    def test_upload_to_s3_client_error(self, mock_boto_client):
        """Test upload_to_s3 returns None when S3 upload fails."""
        # Mock the S3 client to raise an error
        mock_s3 = MagicMock()
        mock_s3.upload_fileobj.side_effect = ClientError(
            {
                "Error": {
                    "Code": "NoSuchBucket",
                    "Message": "The specified bucket does not exist",
                },
            },
            "PutObject",
        )
        mock_boto_client.return_value = mock_s3

        # Create a mock file
        mock_file = MagicMock()
        mock_file.name = "test_image.jpg"
        mock_file.content_type = "image/jpeg"

        # Call the function
        result = upload_to_s3(mock_file)

        # Verify result is None
        self.assertIsNone(result)
