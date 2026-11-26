"""Types shared by the modules."""

from werkzeug.wrappers import Response

# what a view function may return: a redirect or other response, a rendered page, or a page with a status code
ViewResult = Response | str | tuple[str, int]
