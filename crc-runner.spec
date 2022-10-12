Name:           crc-runner
Version:        0.0.1
Release:        1%{?dist}
Summary:        A monitor for OpenShift Local

BuildArch:      noarch

URL:            https://github.com/KevinMGranger/python-crc-systemd
Source0:        %{name}-%{version}.tar.gz

BuildRequires:  python3-devel

Requires:       python3-dbus-next
Requires:       python3-systemd

%description
Run crc as a user, but with ingress as the system.

Runs crc itself as a user-level service, polling it to see if it's healthy.

Coordinates this with a system-level service, so that haproxy can be started once it's ready.



%prep
%autosetup


%build
%configure
%make_build


%install
%make_install


%files



%changelog
* Wed Oct 12 2022 Kevin M Granger <git@kevinmgranger.me>
- Create a package for crc-runner.
