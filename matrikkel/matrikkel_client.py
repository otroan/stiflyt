"""Matrikkel API client library for querying Norwegian property registry data.

This module provides a client for interacting with the Matrikkel API (Statens kartverk).
It supports querying matrikkelenhet (property units) and retrieving owner information.
"""

from typing import List, Any, Optional, Tuple
from dataclasses import dataclass
from zeep import Client, Settings
from zeep.transports import Transport
import requests
from requests.auth import HTTPBasicAuth


@dataclass
class MatrikkelConfig:
    """Configuration for Matrikkel API client."""
    username: str
    password: str
    base_url: str = "https://prodtest.matrikkel.no/matrikkelapi/wsapi/v1"
    klient_identifikasjon: str = "stiflyt3"
    system_version: str = "1.0"
    locale: str = "nb_NO"
    koordinatsystem_kode_id: int = 25833
    bruk_originale_koordinater: bool = False


@dataclass
class MatrikkelIdent:
    """Matrikkel identifier (kommune, gnr, bnr)."""
    kommune: int
    gardsnummer: int
    bruksnummer: int
    festenummer: Optional[int] = None
    seksjonsnummer: Optional[int] = None


@dataclass
class OwnerInfo:
    """Owner information."""
    navn: Optional[str] = None
    adresse: Optional[str] = None
    eierId: Optional[int] = None


class MatrikkelClient:
    """Client for interacting with the Matrikkel API.

    This client manages connections to MatrikkelenhetServiceWS and StoreServiceWS,
    reusing sessions and clients for efficiency.
    """

    def __init__(self, config: MatrikkelConfig):
        """Initialize Matrikkel client with configuration.

        Args:
            config: MatrikkelConfig object with API credentials and settings
        """
        self.config = config
        self._session: Optional[requests.Session] = None
        self._matrikkelenhet_client: Optional[Client] = None
        self._store_client: Optional[Client] = None

    def _get_session(self) -> requests.Session:
        """Get or create a reusable session with authentication."""
        if self._session is None:
            self._session = requests.Session()
            self._session.auth = HTTPBasicAuth(self.config.username, self.config.password)
        return self._session

    def _get_matrikkelenhet_client(self) -> Client:
        """Get or create MatrikkelenhetService client.

        Returns:
            Client object with service binding configured
        """
        if self._matrikkelenhet_client is None:
            session = self._get_session()
            transport = Transport(session=session)
            settings = Settings(strict=False, xml_huge_tree=True)

            wsdl_url = f"{self.config.base_url}/MatrikkelenhetServiceWS?WSDL"
            client = Client(wsdl=wsdl_url, transport=transport, settings=settings)

            # Create service binding - this also sets client.service
            client.create_service(
                "{http://matrikkel.statkart.no/matrikkelapi/wsapi/v1/service/matrikkelenhet}MatrikkelenhetServicePortBinding",
                f"{self.config.base_url}/MatrikkelenhetServiceWS",
            )
            self._matrikkelenhet_client = client
        return self._matrikkelenhet_client

    def _get_store_client(self) -> Client:
        """Get or create StoreService client."""
        if self._store_client is None:
            session = self._get_session()
            transport = Transport(session=session)
            settings = Settings(strict=False, xml_huge_tree=True)

            wsdl_url = f"{self.config.base_url}/StoreServiceWS?WSDL"
            self._store_client = Client(wsdl=wsdl_url, transport=transport, settings=settings)
        return self._store_client

    @staticmethod
    def _find_type(client: Client, type_name: str, namespace_prefixes: Optional[List[str]] = None) -> Optional[Any]:
        """Find a type in a zeep client by trying multiple namespace prefixes."""
        if namespace_prefixes is None:
            namespace_prefixes = ['ns1', 'ns2', 'ns0', 'ns3', 'ns4', 'ns5', 'tns', '']

        for ns_prefix in namespace_prefixes:
            try:
                full_name = f'{ns_prefix}:{type_name}' if ns_prefix else type_name
                return client.get_type(full_name)
            except (KeyError, AttributeError, LookupError):
                continue
        return None

    @staticmethod
    def _extract_id_value(obj: Any) -> int:
        """Extract ID value from various ID object formats."""
        if isinstance(obj, int):
            return obj
        elif hasattr(obj, 'id'):
            return obj.id
        elif hasattr(obj, 'getValue'):
            return obj.getValue()
        elif hasattr(obj, 'value'):
            return obj.value
        else:
            return int(obj)

    def _create_matrikkel_context(self, client: Client) -> Any:
        """Create a MatrikkelContext object using the provided client."""
        MatrikkelContext = self._find_type(client, 'MatrikkelContext')
        if not MatrikkelContext:
            raise RuntimeError("Could not find MatrikkelContext type in client")

        # KoordinatsystemKodeId might be in different namespace depending on the client
        koordinatsystem_prefixes = ['ns2', 'ns3', 'ns1', 'ns0', 'ns4', 'ns5', 'tns', '']
        KoordinatsystemKodeId = self._find_type(client, 'KoordinatsystemKodeId', namespace_prefixes=koordinatsystem_prefixes)
        if not KoordinatsystemKodeId:
            raise RuntimeError("Could not find KoordinatsystemKodeId type in client")

        return MatrikkelContext(
            klientIdentifikasjon=self.config.klient_identifikasjon,
            systemVersion=self.config.system_version,
            locale=self.config.locale,
            brukOriginaleKoordinater=self.config.bruk_originale_koordinater,
            koordinatsystemKodeId=KoordinatsystemKodeId(self.config.koordinatsystem_kode_id),
        )

    @staticmethod
    def _extract_list_items(list_obj: Any) -> List[Any]:
        """Extract items from various list formats (zeep list objects)."""
        if not list_obj:
            return []

        if isinstance(list_obj, list):
            return list_obj
        elif hasattr(list_obj, 'item'):
            items = list_obj.item
            return items if isinstance(items, list) else [items]
        elif hasattr(list_obj, 'getItem'):
            items = list_obj.getItem()
            return items if isinstance(items, list) else [items]

        return []

    def find_matrikkelenhet_id(self, ident: MatrikkelIdent) -> Tuple[Any, Client]:
        """Find matrikkelenhet ID for a given identifier.

        Args:
            ident: MatrikkelIdent object with kommune, gardsnummer, bruksnummer

        Returns:
            Tuple of (MatrikkelenhetId object, client) - client is returned for reuse

        Raises:
            Fault: If the API call fails
            RuntimeError: If types cannot be found
        """
        client = self._get_matrikkelenhet_client()

        # Get types - using known namespace prefixes for MatrikkelenhetServiceWS
        MatrikkelenhetIdent = client.get_type("ns1:MatrikkelenhetIdent")
        MatrikkelContext = client.get_type("ns2:MatrikkelContext")
        KoordinatsystemKodeId = client.get_type("ns3:KoordinatsystemKodeId")

        # Always include festenummer and seksjonsnummer, defaulting to 0 if None
        # This prevents null values from being serialized (which causes Java backend errors)
        matrikkelenhet_ident = MatrikkelenhetIdent(
            kommuneIdent=int(ident.kommune),
            gardsnummer=int(ident.gardsnummer),
            bruksnummer=int(ident.bruksnummer),
            festenummer=int(ident.festenummer if ident.festenummer is not None else 0),
            seksjonsnummer=int(ident.seksjonsnummer if ident.seksjonsnummer is not None else 0),
        )

        ctx = MatrikkelContext(
            klientIdentifikasjon=self.config.klient_identifikasjon,
            systemVersion=self.config.system_version,
            locale=self.config.locale,
            brukOriginaleKoordinater=self.config.bruk_originale_koordinater,
            koordinatsystemKodeId=KoordinatsystemKodeId(self.config.koordinatsystem_kode_id),
        )

        result = client.service.findMatrikkelenhetIdForIdent(
            matrikkelenhetIdent=matrikkelenhet_ident,
            matrikkelContext=ctx,
        )
        return result, client

    def find_matrikkelenhet_ids_batch(self, idents: List[MatrikkelIdent]) -> List[Tuple[MatrikkelIdent, Any, Optional[Exception]]]:
        """Find matrikkelenhet IDs for multiple identifiers in batch.

        Args:
            idents: List of MatrikkelIdent objects

        Returns:
            List of tuples: (MatrikkelIdent, MatrikkelenhetId or None, Exception or None)
            Each tuple represents the result for one identifier.
            If successful, MatrikkelenhetId is returned and Exception is None.
            If failed, MatrikkelenhetId is None and Exception contains the error.
        """
        results = []
        client = None  # Will be created on first call

        for ident in idents:
            try:
                matrikkelenhet_id, client = self.find_matrikkelenhet_id(ident)
                results.append((ident, matrikkelenhet_id, None))
            except Exception as e:
                results.append((ident, None, e))

        return results

    def get_owner_information(self, matrikkelenhet_id: Any, debug: bool = False) -> List[OwnerInfo]:
        """Get owner information for a matrikkelenhet.

        Args:
            matrikkelenhet_id: MatrikkelenhetId object or ID value
            debug: If True, print debug information

        Returns:
            List of OwnerInfo objects

        Raises:
            RuntimeError: If matrikkelenhet_client is not available or types cannot be found
            Fault: If the API call fails
        """
        store_client = self._get_store_client()
        matrikkelenhet_client = self._get_matrikkelenhet_client()

        # Extract ID value and create MatrikkelenhetId object
        matrikkel_id_value = self._extract_id_value(matrikkelenhet_id)
        MatrikkelenhetId = matrikkelenhet_client.get_type("ns1:MatrikkelenhetId")

        # Create the MatrikkelenhetId object - try different parameter patterns
        try:
            matrikkel_id_obj = MatrikkelenhetId(id=int(matrikkel_id_value), objectType='Matrikkelenhet')
        except (TypeError, AttributeError):
            try:
                matrikkel_id_obj = MatrikkelenhetId(value=int(matrikkel_id_value))
            except (TypeError, AttributeError):
                matrikkel_id_obj = MatrikkelenhetId(int(matrikkel_id_value))

        # Create context
        ctx = self._create_matrikkel_context(store_client)

        # Get the Matrikkelenhet object
        matrikkelenhet = store_client.service.getObject(matrikkel_id_obj, ctx)

        if debug:
            print(f"Matrikkelenhet object: {matrikkelenhet}")

        owners = []

        # Extract eierforhold (owner relationships)
        if hasattr(matrikkelenhet, 'eierforhold'):
            eierforhold_list = matrikkelenhet.eierforhold
        elif hasattr(matrikkelenhet, 'getEierforhold'):
            eierforhold_list = matrikkelenhet.getEierforhold()
        else:
            return owners

        # Extract items from the list
        items = self._extract_list_items(eierforhold_list)

        # For each eierforhold, get the person details
        for eierforhold in items:
            owner_info = OwnerInfo()

            # Get eierId
            eier_id = None
            if hasattr(eierforhold, 'eierId'):
                eier_id = eierforhold.eierId
            elif hasattr(eierforhold, 'getEierId'):
                eier_id = eierforhold.getEierId()

            if eier_id:
                # eierId is already a PersonId object - use it directly
                try:
                    person = store_client.service.getObject(eier_id, ctx)

                    # Extract name
                    if hasattr(person, 'navn'):
                        owner_info.navn = person.navn
                    elif hasattr(person, 'getNavn'):
                        owner_info.navn = person.getNavn()

                    # Extract address if available
                    if hasattr(person, 'adresse'):
                        owner_info.adresse = person.adresse
                    elif hasattr(person, 'getAdresse'):
                        owner_info.adresse = person.getAdresse()

                    owners.append(owner_info)
                except Exception as e:
                    # Get the ID value for error message
                    person_id_value = self._extract_id_value(eier_id)
                    if debug:
                        print(f"Warning: Could not get person details for eierId {person_id_value}: {e}")
                    owner_info.eierId = person_id_value
                    owners.append(owner_info)

        return owners

    def get_owners_batch(self, matrikkelenhet_ids: List[Any], debug: bool = False) -> List[Tuple[Any, List[OwnerInfo], Optional[Exception]]]:
        """Get owner information for multiple matrikkelenhet IDs in batch.

        Args:
            matrikkelenhet_ids: List of MatrikkelenhetId objects or ID values
            debug: If True, print debug information

        Returns:
            List of tuples: (matrikkelenhet_id, List[OwnerInfo] or None, Exception or None)
            Each tuple represents the result for one matrikkelenhet_id.
            If successful, List[OwnerInfo] is returned and Exception is None.
            If failed, List[OwnerInfo] is None and Exception contains the error.
        """
        results = []

        for matrikkelenhet_id in matrikkelenhet_ids:
            try:
                owners = self.get_owner_information(matrikkelenhet_id, debug=debug)
                results.append((matrikkelenhet_id, owners, None))
            except Exception as e:
                results.append((matrikkelenhet_id, None, e))

        return results

    def close(self):
        """Close all connections and clean up resources."""
        if self._session:
            self._session.close()
            self._session = None
        self._matrikkelenhet_client = None
        self._store_client = None

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup."""
        self.close()

