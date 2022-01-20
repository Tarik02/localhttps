import asyncio
from typing import List, Tuple
from aiopath import AsyncPath

from localhttps.cert.ca import CertificationAuthority
from localhttps.cmd import Cmd

class Certificate:
    _authority: CertificationAuthority
    _root_path: AsyncPath
    _name: str
    _domain: str

    def __init__(self, authority: CertificationAuthority, root_path: AsyncPath, name: str, domain: str) -> None:
        self._authority = authority
        self._root_path = root_path
        self._name = name
        self._domain = domain

    @property
    def key_path(self) -> AsyncPath:
        return self._root_path/f'{self._name}.key'

    @property
    def csr_path(self) -> AsyncPath:
        return self._root_path/f'{self._name}.csr'

    @property
    def crt_path(self) -> AsyncPath:
        return self._root_path/f'{self._name}.crt'

    @property
    def conf_path(self) -> AsyncPath:
        return self._root_path/f'{self._name}.conf'

    @property
    def common_name(self) -> str:
        return self._domain

    @property
    def email(self) -> str:
        return f'{self._domain}@localhttps'

    @property
    def subject_parts(self) -> List[Tuple[str, str]]:
        return [
            ('C', ''),
            ('ST', ''),
            ('O', ''),
            ('localityName', ''),
            ('commonName', self.common_name),
            ('organizationalUnitName', ''),
            ('emailAddress', self.email),
        ]

    @property
    def subject(self) -> str:
        return ''.join(
            f'/{key}={value}' for (key, value) in self.subject_parts
        ) + '/'

    async def exists(self) -> bool:
        key_exists, csr_exists, crt_exists, conf_exists = await asyncio.gather(
            self.key_path.exists(),
            self.csr_path.exists(),
            self.crt_path.exists(),
            self.conf_path.exists(),
        )
        return key_exists and csr_exists and crt_exists and conf_exists

    async def _build_certificate_conf(self) -> None:
        await self.conf_path.write_text(f'''
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req

[req_distinguished_name]
countryName = Country Name (2 letter code)
countryName_default = US
stateOrProvinceName = State or Province Name (full name)
stateOrProvinceName_default = MN
localityName = Locality Name (eg, city)
localityName_default = Minneapolis
organizationalUnitName	= Organizational Unit Name (eg, section)
organizationalUnitName_default	= Domain Control Validated
commonName = Internet Widgits Ltd
commonName_max	= 64

[ v3_req ]
# Extensions to add to a certificate request
basicConstraints = CA:FALSE
keyUsage = nonRepudiation, digitalSignature, keyEncipherment
subjectAltName = @alt_names

[alt_names]
DNS.1 = {self._domain}
DNS.2 = *.{self._domain}
'''.strip())

    async def _create_private_key(self, cmd: Cmd) -> None:
        await cmd.run(
            'openssl',
            'genrsa',
            '-out', str(await self.key_path.resolve()),
            '2048',
        )

    async def _create_signing_request(self, cmd: Cmd) -> None:
        await cmd.run(
            'openssl',
            'req',
            '-new',
            '-key', str(await self.key_path.resolve()),
            '-out', str(await self.csr_path.resolve()),
            '-subj', self.subject,
            '-config', str(await self.conf_path.resolve()),
        )

    async def create(self, cmd: Cmd) -> None:
        await self.delete()
        await self._root_path.mkdir(parents=True, exist_ok=True)

        await asyncio.gather(
            self._build_certificate_conf(),
            self._create_private_key(cmd),
        )
        await self._create_signing_request(cmd)

        params = [
            '-req',
            '-sha256',
            '-days', '730',
            '-CA', str(await self._authority.pem_path.resolve()),
            '-CAkey', str(await self._authority.key_path.resolve()),
            '-CAserial', str(await self._authority.srl_path.resolve()),
        ]

        if not await self._authority.srl_path.exists():
            params.append('-CAcreateserial')

        params = [
            *params,
            '-in', str(await self.csr_path.resolve()),
            '-out', str(await self.crt_path.resolve()),
            '-extensions', 'v3_req',
            '-extfile', str(await self.conf_path.resolve()),
        ]

        await cmd.run('openssl', 'x509', *params)
        await self.crt_path.chmod(0o644)
        await self.key_path.chmod(0o644)

    async def delete(self) -> None:
        await asyncio.gather(
            self.key_path.unlink(missing_ok=True),
            self.csr_path.unlink(missing_ok=True),
            self.crt_path.unlink(missing_ok=True),
            self.conf_path.unlink(missing_ok=True),
        )
        if await self._root_path.exists():
            async for _ in self._root_path.glob('*'):
                return
            await self._root_path.rmdir()
