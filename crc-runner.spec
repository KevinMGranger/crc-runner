Name:           crc-runner
License:        FIXME
Version:        0.0.1
Release:        1%{?dist}
Summary:        A monitor for OpenShift Local

URL:            https://github.com/KevinMGranger/python-crc-systemd
Source0:        %{name}-%{version}.tar.gz

BuildRequires:  python3-devel pyproject-rpm-macros
BuildRequires:  systemd-rpm-macros systemd-devel gcc
BuildRequires:  just
BuildArch:      noarch

Requires:       python3
Requires:       python3-dbus-next
Requires:       python3-systemd

%description
Run crc as a user, but with ingress as the system.

Runs crc itself as a user-level service, polling it to see if it's healthy.

Coordinates this with a system-level service, so that haproxy can be started once it's ready.

%generate_buildrequires
%pyproject_buildrequires


%prep
%autosetup


%build
%pyproject_wheel
# %configure
# %make_build # why isn't this documented
# make build # TODO: gonna keep them uncompiled for now


%install
%pyproject_install

just install-user-services %{_userunitdir}
just install-system-services %{_unitdir}

%post
%systemd_post crc.service
%systemd_user_post crc.service
%systemd_user_post crc-log.service

%files



%changelog
* Wed Oct 12 2022 Kevin M Granger <git@kevinmgranger.me>
- Create a package for crc-runner.
