"""ACM certificate for the UI custom domain.

Lives in us-east-1 because CloudFront only accepts certs from us-east-1.
The cert is consumed cross-region by NseQuantStack in the primary region.
"""

from aws_cdk import (
    Stack,
    aws_certificatemanager as acm,
    aws_route53 as route53,
)
from constructs import Construct


class CertStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        domain_name: str,
        hosted_zone_id: str,
        hosted_zone_name: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        zone = route53.HostedZone.from_hosted_zone_attributes(
            self,
            "Zone",
            hosted_zone_id=hosted_zone_id,
            zone_name=hosted_zone_name,
        )

        self.certificate = acm.Certificate(
            self,
            "Cert",
            domain_name=domain_name,
            validation=acm.CertificateValidation.from_dns(zone),
        )
