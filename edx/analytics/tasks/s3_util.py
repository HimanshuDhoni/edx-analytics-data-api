"""
Utility methods for interacting with S3 via boto.
"""

from fnmatch import fnmatch
from urlparse import urlparse

from boto.s3.key import Key
from luigi.s3 import S3Client


def get_s3_bucket_key_names(url):
    """Extract the bucket and key names from a S3 URL"""
    parts = urlparse(url)
    return (parts.netloc.strip('/'), parts.path.strip('/'))


def join_as_s3_url(bucket, root, path):
    """Combine bucket name, root path and relative path into a S3 URL"""
    return 's3://{0}/{1}/{2}'.format(bucket, root, path)


def get_s3_key(s3_conn, url):
    """Returns an S3 key for use in further boto actions."""
    bucket_name, key_name = get_s3_bucket_key_names(url)
    bucket = s3_conn.get_bucket(bucket_name)
    key = bucket.get_key(key_name)
    return key


def generate_s3_sources(s3_conn, source, patterns):
    """
    Returns a list of S3 sources that match filters.

    Args:

      s3_conn: a boto connection to S3.
      source:  a url to S3.
      patterns:  a list of strings, each of which defines a pattern to match.

    Yields:

      (bucket, root, path) tuples for each matching file on S3.

      where `bucket` and `root` are derived from the source url,
      and `path` is a matching path relative to the `source`.

    Does not include zero-length files.
    """
    bucket_name, root = get_s3_bucket_key_names(source)

    bucket = s3_conn.get_bucket(bucket_name)

    # Skip keys that have zero size.  This allows directories
    # to be skipped, but also skips legitimate files that are
    # also zero-length.
    keys = (s.key for s in bucket.list(root) if s.size > 0)

    # Make paths relative by removing root
    paths = (k[len(root):].lstrip('/') for k in keys)

    # Filter only paths that match the include patterns
    paths = _filter_matches(patterns, paths)

    return ((bucket.name, root, path) for path in paths)


def _filter_matches(patterns, names):
    """Return only key names that match any of the include patterns."""
    func = lambda n: any(fnmatch(n, p) for p in patterns)
    return (n for n in names if func(n))


class RestrictedPermissionsS3Client(S3Client):
    """
    S3 client that requires minimal permissions to write objects to a bucket.

    It should only require PutObject and PutObjectAcl permissions in order to write to the target bucket.
    """
    # TODO: Make this behavior configurable and submit this change upstream.

    def put(self, local_path, destination_s3_path):
        """Put an object stored locally to an S3 path."""
        (bucket, key) = self._path_to_bucket_and_key(destination_s3_path)

        # Boto will list all of the keys in the bucket if it is passed "validate=True" this requires an additional
        # permission.  We want to minimize the set of required permissions so we get a reference to the bucket without
        # validating that it exists.
        s3_bucket = self.s3.get_bucket(bucket, validate=False)

        # By default, AWS does not apply an ACL to keys that are put into a bucket from another account. Having no ACL
        # at all effectively renders the object useless since it cannot be read or anything. The only workaround we
        # found was to explicitly set the ACL policy when putting the object.
        s3_key = Key(s3_bucket)
        s3_key.key = key
        s3_key.set_contents_from_filename(local_path, policy='bucket-owner-full-control')
