"""Bounded public S3 diagnostic categories; never return response messages."""
import xml.etree.ElementTree as ET

MAX_RESPONSE = 65536
S3_CODES = frozenset({"SlowDown", "ServiceUnavailable", "InternalError", "AccessDenied", "InvalidAccessKeyId",
                      "SignatureDoesNotMatch", "RequestTimeout", "InvalidArgument", "InvalidBucketName",
                      "PermanentRedirect", "TemporaryRedirect", "AllAccessDisabled", "OperationAborted",
                      "BadDigest", "EntityTooLarge", "BucketAlreadyExists", "BucketAlreadyOwnedByYou",
                      "TooManyBuckets", "AccountProblem", "BadContent", "PreconditionFailed", "InvalidDigest",
                      "MetadataTooLarge", "InvalidRequest", "InvalidSecurity", "NotImplemented", "Redirect",
                      "RequestTimeTooSkewed", "NoSuchBucket", "NoSuchKey"})


def response_summary(status, body):
    result = {"http_status": status if type(status) is int and 100 <= status <= 599 else None,
              "xml_code": "UNKNOWN", "spam_refusal": False}
    if not isinstance(body, bytes) or len(body) > MAX_RESPONSE:
        return result
    result["spam_refusal"] = b"appears to be spam" in body.lower()
    if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        return result
    try:
        root = ET.fromstring(body)
        if root.tag.rsplit("}", 1)[-1] == "Error":
            codes = [child.text for child in root if child.tag.rsplit("}", 1)[-1] == "Code"]
            if len(codes) == 1 and codes[0] in S3_CODES:
                result["xml_code"] = codes[0]
    except (ET.ParseError, ValueError):
        pass
    return result
