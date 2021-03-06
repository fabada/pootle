#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (C) Pootle contributors.
#
# This file is a part of the Pootle project. It is distributed under the GPL3
# or later license. See the LICENSE file for a copy of the license and the
# AUTHORS file for copyright and authorship information.

from django.contrib.auth import get_user_model
from django.core.validators import ValidationError

import pytest

from allauth.account.models import EmailAddress

import accounts
from pootle_store.util import FUZZY, TRANSLATED

from tests.fixtures.models.store import (TEST_EVIL_UPDATE_PO,
                                         _create_submission_and_suggestion,
                                         _create_comment_on_unit)


def _make_evil_member_updates(store, evil_member):
    # evil_member makes following changes:
    #   - rejects member's suggestion on unit
    #   - changes unit
    #   - adds another suggestion on unit
    #   - accepts their own suggestion
    #   - adds a comment on unit
    #   - adds another unit
    member_suggestion = store.units[0].get_suggestions().first()
    unit = store.units[0]
    unit.reject_suggestion(member_suggestion,
                           store.units[0].store.translation_project,
                           evil_member)
    _create_submission_and_suggestion(store,
                                      evil_member,
                                      filename=TEST_EVIL_UPDATE_PO,
                                      suggestion="EVIL SUGGESTION")
    evil_suggestion = store.units[0].get_suggestions().first()
    store.units[0].accept_suggestion(evil_suggestion,
                                     store.units[0].store.translation_project,
                                     evil_member)
    _create_comment_on_unit(store.units[0], evil_member, "EVIL COMMENT")


def _test_user_merged(unit, src_user, target_user):
    # TODO: test reviews and comments
    if src_user.id:
        assert src_user.submitted.count() == 0
        assert src_user.suggestions.count() == 0

    assert target_user.submitted.first() == unit
    assert target_user.suggestions.first() == unit.get_suggestions().first()


def _test_before_evil_user_updated(store, member, teststate=False):
    unit = store.units[0]

    # Unit state is fuzzy
    assert unit.state == FUZZY

    # Unit target was updated.
    assert unit.target_f == "Hello, world UPDATED"
    assert unit.submitted_by == member

    # But member also added a suggestion to the unit.
    assert unit.get_suggestions().count() == 1
    assert unit.get_suggestions().first().user == member

    # And added a comment on the unit.
    assert unit.translator_comment == "NICE COMMENT"
    assert unit.commented_by == member

    # Only 1 unit round here.
    assert store.units.count() == 1


def _test_after_evil_user_updated(store, evil_member):
    unit = store.units[0]

    # Unit state is TRANSLATED
    assert unit.state == TRANSLATED

    # Evil member has accepted their own suggestion.
    assert unit.target_f == "EVIL SUGGESTION"
    assert unit.submitted_by == evil_member

    # And rejected member's.
    assert unit.get_suggestions().count() == 0

    # And added their own comment.
    assert unit.translator_comment == "EVIL COMMENT"
    assert unit.commented_by == evil_member

    # Evil member has added another unit.
    assert store.units.count() == 2
    assert store.units[1].target_f == "Goodbye, world EVIL"
    assert store.units[1].submitted_by == evil_member


def _test_user_purging(store, member, evil_member, purge):

    first_revision = store.get_max_unit_revision()
    unit = store.units[0]

    # Get intitial change times
    initial_submission_time = unit.submitted_on
    initial_comment_time = unit.commented_on
    initial_review_time = unit.reviewed_on

    # Test state before evil user has updated.
    _test_before_evil_user_updated(store, member, True)

    # Update as evil member
    _make_evil_member_updates(store, evil_member)

    # Revision has increased
    latest_revision = store.get_max_unit_revision()
    assert latest_revision > first_revision

    unit = store.units[0]

    # Test submitted/commented/reviewed times on the unit
    # This is an unreliable test on mysql due to datetime precision
    if unit.submitted_on.time().microsecond != 0:

        # Times have changed
        assert unit.submitted_on != initial_submission_time
        assert unit.commented_on != initial_comment_time
        assert unit.reviewed_on != initial_review_time

    # Test state after evil user has updated.
    _test_after_evil_user_updated(store, evil_member)

    # Purge evil_member
    purge(evil_member)

    # Revision has increased again.
    assert store.get_max_unit_revision() > latest_revision

    unit = store.units[0]

    # Times are back to previous times - by any precision
    assert unit.submitted_on == initial_submission_time
    assert unit.commented_on == initial_comment_time
    assert unit.reviewed_on == initial_review_time

    # State is be back to how it was before evil user updated.
    _test_before_evil_user_updated(store, member)


@pytest.mark.django_db
def test_merge_user(en_tutorial_po, member, member2):
    """Test merging user to another user."""
    unit = _create_submission_and_suggestion(en_tutorial_po, member)
    accounts.utils.UserMerger(member, member2).merge()
    _test_user_merged(unit, member, member2)


@pytest.mark.django_db
def test_delete_user(en_tutorial_po, member, nobody):
    """Test default behaviour of User.delete - merge to nobody"""
    unit = _create_submission_and_suggestion(en_tutorial_po, member)
    member.delete()
    _test_user_merged(unit, member, nobody)


@pytest.mark.django_db
def test_purge_user(en_tutorial_po_member_updated,
                    member, evil_member):
    """Test purging user using `purge_user` function"""
    _test_user_purging(en_tutorial_po_member_updated,
                       member, evil_member,
                       lambda m: accounts.utils.UserPurger(m).purge())


@pytest.mark.django_db
def test_delete_purge_user(en_tutorial_po_member_updated,
                           member, evil_member):
    """Test purging user using `User.delete(purge=True)`"""
    _test_user_purging(en_tutorial_po_member_updated,
                       member, evil_member,
                       lambda m: m.delete(purge=True))


@pytest.mark.django_db
def test_verify_user(member_with_email):
    """Test verifying user using `verify_user` function"""

    # Member is not currently verified
    with pytest.raises(EmailAddress.DoesNotExist):
        EmailAddress.objects.get(user=member_with_email, verified=True)

    # Verify user
    accounts.utils.verify_user(member_with_email)

    # Get the verified email object
    EmailAddress.objects.get(user=member_with_email,
                             email="member_with_email@this.test",
                             primary=True, verified=True)


@pytest.mark.django_db
def test_verify_user_empty_email(trans_member):
    """Test verifying user using `verify_user` function"""

    # Member has no EmailAddress set
    with pytest.raises(EmailAddress.DoesNotExist):
        EmailAddress.objects.get(user=trans_member)

    # Email is not set on User either
    assert trans_member.email == ''

    # Verify user - raises ValidationError
    with pytest.raises(ValidationError):
        accounts.utils.verify_user(trans_member)

    # User still has no email
    with pytest.raises(EmailAddress.DoesNotExist):
        EmailAddress.objects.get(user=trans_member)


@pytest.mark.django_db
def test_verify_user_after_update_email(trans_member):
    """Test verifying user using `verify_user` function"""

    # Member has no EmailAddress set
    with pytest.raises(EmailAddress.DoesNotExist):
        EmailAddress.objects.get(user=trans_member)

    # Email is not set on User either
    assert trans_member.email == ''

    # Use util to set email
    accounts.utils.update_user_email(trans_member,
                                     "trans_member@this.test")

    # Verify user
    accounts.utils.verify_user(trans_member)

    # Email verified
    EmailAddress.objects.get(user=trans_member,
                             primary=True, verified=True)


@pytest.mark.django_db
def test_verify_user_duplicate_email(trans_member, member_with_email):
    """Test verifying user using `verify_user` function"""

    # trans_member steals member_with_email's email
    trans_member.email = member_with_email.email

    # And can't verify with it
    with pytest.raises(ValidationError):
        accounts.utils.verify_user(trans_member)

    # Email not verified
    with pytest.raises(EmailAddress.DoesNotExist):
        EmailAddress.objects.get(user=trans_member,
                                 primary=True, verified=True)


@pytest.mark.django_db
def test_verify_user_without_existing_email(trans_member):
    """Test verifying user using `verify_user` function"""

    member = trans_member

    # Member has no allauth.EmailAddress object
    with pytest.raises(EmailAddress.DoesNotExist):
        EmailAddress.objects.get(user=member)

    # Give member an email - but don't save, as this would trigger
    # allauth.EmailAddress creation
    member.email = "member@this.test"

    # Verify user
    accounts.utils.verify_user(member)

    # Get the verified email object
    EmailAddress.objects.get(user=member, email="member@this.test",
                             primary=True, verified=True)

    # This does not update the member object!
    assert get_user_model().objects.get(pk=member.pk).email == ""


@pytest.mark.django_db
def test_verify_user_with_primary_and_non_primary_email_object(trans_member):
    """Test verifying user using `verify_user` function that has an
    allauth.EmailAddress object but is not yet verified
    """
    member = trans_member

    # Give member an email
    member.email = "member@this.test"

    # Create the unverified non-primary email object
    EmailAddress.objects.create(user=member, email=member.email,
                                primary=False, verified=False)

    # Create unverified primary email object
    EmailAddress.objects.create(user=member, email="otheremail@this.test",
                                primary=True, verified=False)

    # Verify user
    accounts.utils.verify_user(member)

    # Get the verified email object - the primary address is used
    EmailAddress.objects.get(user=member, email="otheremail@this.test",
                             primary=True, verified=True)


@pytest.mark.django_db
def test_verify_user_already_verified(member_with_email):
    """Test verifying user using `verify_user` function that has an
    allauth.EmailAddress object but is not yet verified
    """
    # Verify user
    accounts.utils.verify_user(member_with_email)

    # Verify user again - raises ValueError
    with pytest.raises(ValueError):
        accounts.utils.verify_user(member_with_email)

    # Get the verified email object
    EmailAddress.objects.get(user=member_with_email,
                             email=member_with_email.email,
                             primary=True, verified=True)


@pytest.mark.django_db
def test_update_user_email_without_existing_email(trans_member):
    """Test updating user email using `update_user_email` function"""
    assert trans_member.email == ""

    # Trans_Member has no EmailAddress object
    with pytest.raises(EmailAddress.DoesNotExist):
        EmailAddress.objects.get(user=trans_member)

    accounts.utils.update_user_email(trans_member, "trans_member@this.test")

    # User.email has been set
    assert trans_member.email == "trans_member@this.test"

    # member still has no EmailAddress object
    with pytest.raises(EmailAddress.DoesNotExist):
        EmailAddress.objects.get(user=trans_member)


@pytest.mark.django_db
def test_update_user_email_with_unverified_acc(member_with_email):
    """Test updating user email using `update_user_email` function"""

    # Create an unverified primary email object
    EmailAddress.objects.create(user=member_with_email,
                                email=member_with_email.email,
                                primary=True, verified=False).save()

    accounts.utils.update_user_email(member_with_email,
                                     "new_email_address@this.test")

    # Both User.email and EmailAddress.email should be updated for user
    email_address = EmailAddress.objects.get(user=member_with_email)
    assert member_with_email.email == "new_email_address@this.test"
    assert email_address.email == "new_email_address@this.test"

    # Doesnt affect verification
    assert email_address.verified is False


@pytest.mark.django_db
def test_update_user_email_with_multiple_email_addresses(member_with_email):
    """Test updating user email using `update_user_email` function"""

    # Create primary/secondary email addresses
    EmailAddress.objects.create(user=member_with_email,
                                email=member_with_email.email,
                                primary=True, verified=True).save()
    EmailAddress.objects.create(user=member_with_email,
                                email="alt_email@this.test",
                                primary=False, verified=False).save()

    accounts.utils.update_user_email(member_with_email,
                                     "new_email@this.test")

    # Both User.email and EmailAddress.email should be updated for user
    email_address = EmailAddress.objects.get(user=member_with_email,
                                             primary=True)
    assert member_with_email.email == "new_email@this.test"
    assert email_address.email == "new_email@this.test"

    # Doesnt affect other email address tho
    alt_email_address = EmailAddress.objects.get(user=member_with_email,
                                                 primary=False)
    assert alt_email_address.email == "alt_email@this.test"


@pytest.mark.django_db
def test_update_user_email_bad_invalid_email(member_with_email):
    with pytest.raises(ValidationError):
        accounts.utils.update_user_email(member_with_email,
                                         "NOT_AN_EMAIL_ADDRESS")


@pytest.mark.django_db
def test_update_user_email_bad_invalid_duplicate(member_with_email, member2):

    # Create 2 emails for member2
    member2.email = "member2@this.test"
    member2.save()
    (EmailAddress.objects
                 .create(user=member2,
                         email=member2.email,
                         primary=True, verified=True)).save()
    (EmailAddress.objects
                 .create(user=member2,
                         email="alt_email@this.test",
                         primary=False,
                         verified=False)).save()

    # Member cannot update with either of member2's emails
    with pytest.raises(ValidationError):
        accounts.utils.update_user_email(member_with_email,
                                         member2.email)
    with pytest.raises(ValidationError):
        accounts.utils.update_user_email(member_with_email,
                                         "alt_email@this.test")
