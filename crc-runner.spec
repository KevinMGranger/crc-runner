Name:           crc-runner
License:        FIXME
Version:        0.0.1
Release:        1%{?dist}
Summary:        A monitor for OpenShift Local

URL:            https://github.com/KevinMGranger/crc-runner
Source0:        %{name}-%{version}.tar.gz

BuildRequires:  python3-devel pyproject-rpm-macros python3-hatchling
BuildRequires:  systemd-rpm-macros systemd-devel gcc
BuildRequires:  python3-systemd
BuildRequires:  just
BuildArch:      noarch

Requires:       python3
Requires:       python3-dbus-next
Requires:       python3-systemd

%description
Run crc as a user, but with ingress as the system.

Runs crc itself as a user-level service, polling it to see if it's healthy.

Coordinates this with a system-level service, so that haproxy can be started once it's ready.


%prep
%autosetup

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files crc_runner


mkdir -p %{buildroot}/%{_userunitdir} %{buildroot}/%{_unitdir}
just install-user-services %{buildroot}/%{_userunitdir}
just install-system-service %{buildroot}/%{_unitdir}


mkdir -p %{buildroot}/%{_libexecdir}

cat > %{buildroot}/%{_libexecdir}/crc-runner <<EOF
#!%{python3} -%{py3_shebang_flags}
from crc_runner.__main__ import main
import sys
import os

print(f"running from {main.__file__=} {sys.path=} {os.environ.get('PYTHONPATH', '')=}")

main()

EOF

chmod +x %{buildroot}/%{_libexecdir}/crc-runner 

%check
%pyproject_check_import

%post
%systemd_post crc.service
%systemd_user_post crc.service
%systemd_user_post crc-log.service

%files -f %{pyproject_files}
%{_libexecdir}/crc-runner

%{_userunitdir}/crc.service
%{_userunitdir}/crc-log.service
%{_unitdir}/crc.service



%changelog
* Wed Oct 12 2022 Kevin M Granger <git@kevinmgranger.me>
- Create a package for crc-runner.
