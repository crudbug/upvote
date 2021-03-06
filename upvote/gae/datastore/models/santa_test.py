# Copyright 2017 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS-IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Unit tests for santa.py."""

import datetime

import mock

from google.appengine.ext import db
from google.appengine.ext import ndb

from upvote.gae.datastore import test_utils
from upvote.gae.datastore import utils
from upvote.gae.datastore.models import santa
from upvote.gae.lib.testing import basetest
from upvote.gae.shared.common import settings
from upvote.shared import constants


class SantaModelTest(basetest.UpvoteTestCase):
  """Test Santa Models."""

  def setUp(self):

    super(SantaModelTest, self).setUp()

    self.santa_blockable = santa.SantaBlockable(
        id='aaaabbbbccccdddd',
        id_type=constants.ID_TYPE.SHA256,
        blockable_hash='aaaabbbbccccdddd',
        file_name='Mac.app',
        publisher='Arple',
        product_name='New Shiny',
        version='2.0')

    self.santa_certificate = santa.SantaCertificate(
        id='mmmmnnnnoooopppp',
        id_type=constants.ID_TYPE.SHA256,
        blockable_hash='mmmmnnnnoooopppp',
        file_name='MagicCert',
        publisher='Total Legit CA',
        version='7.0',
        common_name='Trustee',
        organization='Big Lucky',
        organizational_unit='The Unit')

    quarantine = santa.QuarantineMetadata(
        data_url='http://notbad.com',
        referer_url='http://sourceforge.com',
        downloaded_dt=datetime.datetime.utcnow(),
        agent_bundle_id='123456')

    now = datetime.datetime.utcnow()
    self.santa_event = santa.SantaEvent(
        blockable_key=self.santa_blockable.key,
        event_type=constants.EVENT_TYPE.ALLOW_BINARY,
        file_name='Mac.app',
        file_path='/',
        executing_user='foo',
        first_blocked_dt=now,
        last_blocked_dt=now,
        quarantine=quarantine)

    self.santa_blockable.put()
    self.santa_certificate.put()
    self.santa_event.put()

    self.PatchEnv(settings.ProdEnv, ENABLE_BIGQUERY_STREAMING=True)


class SantaBlockableTest(SantaModelTest):

  def testToDict_ContainsOs(self):
    with self.LoggedInUser():
      the_dict = self.santa_blockable.to_dict()
      self.assertEqual(
          constants.PLATFORM.MACOS,
          the_dict.get('operating_system_family', None))

  def testToDict_ContainsIsVotingAllowed(self):
    blockable = test_utils.CreateBlockable()
    with self.LoggedInUser():
      self.assertIn('is_voting_allowed', blockable.to_dict())

  def testIsVotingAllowed_CertIsBlacklisted(self):
    """IsVotingAllowed() called on blockable signed by a blacklisted cert."""
    blockable_cert = test_utils.CreateSantaBlockable()
    blockable = test_utils.CreateSantaBlockable(cert_key=blockable_cert.key)
    test_utils.CreateSantaRule(
        blockable_cert.key,
        rule_type=constants.RULE_TYPE.CERTIFICATE,
        policy=constants.RULE_POLICY.BLACKLIST)

    with self.LoggedInUser():
      allowed, reason = blockable.IsVotingAllowed()

    self.assertFalse(allowed)
    self.assertIsNotNone(reason)

  def testIsVotingAllowed_Admin_CertIsBlacklisted(self):
    """IsVotingAllowed() called on blockable signed by a blacklisted cert."""
    blockable_cert = test_utils.CreateSantaBlockable()
    blockable = test_utils.CreateSantaBlockable(cert_key=blockable_cert.key)
    test_utils.CreateSantaRule(
        blockable_cert.key,
        rule_type=constants.RULE_TYPE.CERTIFICATE,
        policy=constants.RULE_POLICY.BLACKLIST)

    with self.LoggedInUser(admin=True):
      _, reason = blockable.IsVotingAllowed()

      # Ensure voting isn't disabled because of the blacklisted cert.
      self.assertNotEqual(
          constants.VOTING_PROHIBITED_REASONS.BLACKLISTED_CERT, reason)

  def testIsVotingAllowed_CallTheSuper(self):
    santa_blockable = test_utils.CreateSantaBlockable()
    with self.LoggedInUser():
      with mock.patch.object(
          santa.base.Blockable, 'IsVotingAllowed') as mock_method:
        santa_blockable.IsVotingAllowed()
        self.assertTrue(mock_method.called)

  def testChangeState_Persists(self):
    self.santa_blockable.ChangeState(constants.STATE.SUSPECT)
    self.assertBigQueryInsertions([constants.BIGQUERY_TABLE.BINARY])

  def testChangeState_BinaryRowCreation_NoBlockableHash(self):

    hashless_santa_blockable = santa.SantaBlockable(
        id='aaaabbbbccccdddd',
        id_type=constants.ID_TYPE.SHA256,
        file_name='Whatever.app')
    hashless_santa_blockable.ChangeState(constants.STATE.SUSPECT)

    self.assertBigQueryInsertions([constants.BIGQUERY_TABLE.BINARY])

  def testResetState(self):
    self.santa_blockable.ResetState()
    self.assertBigQueryInsertions([constants.BIGQUERY_TABLE.BINARY])


class SantaCertificateTest(SantaModelTest):

  def testPersistsStateChange(self):
    self.santa_certificate.ChangeState(constants.STATE.SUSPECT)
    self.assertBigQueryInsertions([constants.BIGQUERY_TABLE.CERTIFICATE])

  def testResetsState(self):
    self.santa_certificate.ResetState()
    self.assertBigQueryInsertions([constants.BIGQUERY_TABLE.CERTIFICATE])


class SantaEventTest(SantaModelTest):

  def testRunByLocalAdminSantaEvent(self):
    self.assertFalse(self.santa_event.run_by_local_admin)

    self.santa_event.executing_user = constants.LOCAL_ADMIN.MACOS
    self.assertTrue(self.santa_event.run_by_local_admin)

  def testDedupeSantaEvent(self):
    later_dt = (
        self.santa_event.last_blocked_dt + datetime.timedelta(seconds=1))
    new_event = utils.CopyEntity(
        self.santa_event,
        quarantine=None,
        event_type=constants.EVENT_TYPE.BLOCK_CERTIFICATE,
        last_blocked_dt=later_dt)

    self.santa_event.Dedupe(new_event)

    self.assertEqual(
        constants.EVENT_TYPE.BLOCK_CERTIFICATE, self.santa_event.event_type)
    self.assertIsNotNone(self.santa_event.quarantine)

  def testDedupeSantaEvent_AddOldQuarantineData(self):
    quarantine = self.santa_event.quarantine
    self.santa_event.quarantine = None
    self.santa_event.put()

    earlier_dt = (
        self.santa_event.first_blocked_dt - datetime.timedelta(seconds=1))
    new_event = utils.CopyEntity(
        self.santa_event,
        quarantine=quarantine,
        first_blocked_dt=earlier_dt)

    self.santa_event.Dedupe(new_event)

    self.assertIsNotNone(self.santa_event.quarantine)

  def testDedupeSantaEvent_AddNewerQuarantineData(self):
    new_quarantine = utils.CopyEntity(
        self.santa_event.quarantine, data_url='http://3vil.com')

    later_dt = (
        self.santa_event.last_blocked_dt + datetime.timedelta(seconds=1))
    new_event = utils.CopyEntity(
        self.santa_event,
        quarantine=new_quarantine,
        last_blocked_dt=later_dt)

    self.santa_event.Dedupe(new_event)

    self.assertEqual(
        'http://3vil.com', self.santa_event.quarantine.data_url)

  def testGiantQuarantineUrl(self):
    # Ensure URLs that exceed the NDB size limit for indexed properties (1500
    # bytes) may be set on QuarantineMetadata URL fields.
    self.santa_event.quarantine.data_url = 'http://3vil.com/' + 'a' * 1500
    self.santa_event.put()


class SantaBundleTest(SantaModelTest):

  def testIgnoreCalculateScoreBeforeUpload(self):
    bundle = test_utils.CreateSantaBundle(uploaded_dt=None)
    test_utils.CreateVote(bundle)

    # Trigger the SantaBundle.score ComputedProperty calculation.
    bundle.put()

    # The score should have not reflected the real score until the bundle is
    # uploaded.
    self.assertEqual(0, bundle.key.get().score)

  def testTranslatePropertyQuery_CertId(self):
    field, val = 'cert_id', 'bar'

    new_field, new_val = santa.SantaBundle.TranslatePropertyQuery(field, val)

    self.assertEqual(val, ndb.Key(urlsafe=new_val).id())
    self.assertEqual('main_cert_key', new_field)

  def testTranslatePropertyQuery_CertId_NoQueryValue(self):
    field, val = 'cert_id', None

    new_field, new_val = santa.SantaBundle.TranslatePropertyQuery(field, val)

    self.assertIsNone(new_val)
    self.assertEqual('main_cert_key', new_field)

  def testTranslatePropertyQuery_NotCertId(self):
    pair = ('foo', 'bar')
    self.assertEqual(pair, santa.SantaBundle.TranslatePropertyQuery(*pair))

  def testIsVotingAllowed_BundleUpload(self):
    bundle = test_utils.CreateSantaBundle(uploaded_dt=None)
    self.assertFalse(bundle.has_been_uploaded)

    allowed, reason = bundle.IsVotingAllowed()

    self.assertFalse(allowed)
    self.assertEqual(
        constants.VOTING_PROHIBITED_REASONS.UPLOADING_BUNDLE, reason)

  def testIsVotingAllowed_HasFlaggedBinary(self):
    # First, create two unflagged binaries.
    blockables = test_utils.CreateSantaBlockables(2)
    bundle = test_utils.CreateSantaBundle(bundle_binaries=blockables)

    with self.LoggedInUser():
      allowed, reason = bundle.IsVotingAllowed()
      self.assertTrue(allowed)

      # Now flag one of the binaries.
      blockables[0].flagged = True
      blockables[0].put()

      allowed, reason = bundle.IsVotingAllowed()
      self.assertFalse(allowed)
      self.assertEqual(
          constants.VOTING_PROHIBITED_REASONS.FLAGGED_BINARY, reason)

  def testIsVotingAllowed_HasFlaggedCert(self):
    blockable = test_utils.CreateSantaBlockable(
        cert_key=self.santa_certificate.key)
    bundle = test_utils.CreateSantaBundle(bundle_binaries=[blockable])

    with self.LoggedInUser():
      allowed, reason = bundle.IsVotingAllowed()
      self.assertTrue(allowed)

      self.santa_certificate.flagged = True
      self.santa_certificate.put()

      allowed, reason = bundle.IsVotingAllowed()
      self.assertFalse(allowed)
      self.assertEqual(constants.VOTING_PROHIBITED_REASONS.FLAGGED_CERT, reason)

  def testIsVotingAllowed_DisableHasFlaggedChecks(self):
    blockables = test_utils.CreateSantaBlockables(26)
    bundle = test_utils.CreateSantaBundle(bundle_binaries=blockables)

    # Flag one of the binaries.
    blockables[0].flagged = True
    blockables[0].put()

    with self.LoggedInUser():
      # Ensure that the normal call succeeds in finding the flagged binary.
      allowed, reason = bundle.IsVotingAllowed()
      self.assertFalse(allowed)
      self.assertEqual(
          constants.VOTING_PROHIBITED_REASONS.FLAGGED_BINARY, reason)

      # In a transaction, the 26 searched blockables should exceed the allowed
      # limit of 25.
      with self.assertRaises(db.BadRequestError):
        ndb.transaction(
            lambda: bundle.IsVotingAllowed(enable_flagged_checks=True), xg=True)

      # With the checks disabled, IsVotingAllowed shouldn't raise an exception.
      def Test():
        allowed, reason = bundle.IsVotingAllowed(enable_flagged_checks=False)
        self.assertTrue(allowed)
        self.assertIsNone(reason)

      ndb.transaction(Test, xg=True)

  def testIsVotingAllowed_CallTheSuper(self):
    bundle = test_utils.CreateSantaBundle()
    with self.LoggedInUser():
      with mock.patch.object(
          santa.base.Blockable, 'IsVotingAllowed') as mock_method:
        bundle.IsVotingAllowed()
        self.assertTrue(mock_method.called)

  def testToDict(self):
    bundle = test_utils.CreateSantaBundle()
    with self.LoggedInUser():
      dict_ = bundle.to_dict()
    self.assertTrue(dict_['has_been_uploaded'])
    self.assertIsNone(dict_['cert_id'])

  def testToDict_CertId(self):
    blockable = test_utils.CreateSantaBlockable(
        cert_key=self.santa_certificate.key)
    bundle = test_utils.CreateSantaBundle(
        main_cert_key=self.santa_certificate.key,
        bundle_binaries=[blockable])
    with self.LoggedInUser():
      dict_ = bundle.to_dict()
    self.assertTrue(dict_['has_been_uploaded'])
    self.assertEqual(self.santa_certificate.key.id(), dict_['cert_id'])

  def testPersistsStateChange(self):
    bundle = test_utils.CreateSantaBundle(uploaded_dt=None)
    bundle.ChangeState(constants.STATE.SUSPECT)
    self.assertBigQueryInsertions([constants.BIGQUERY_TABLE.BUNDLE])

  def testResetsState(self):
    bundle = test_utils.CreateSantaBundle(uploaded_dt=None)
    bundle.ResetState()
    self.assertBigQueryInsertions([constants.BIGQUERY_TABLE.BUNDLE])


class SantaHostTest(SantaModelTest):

  def testGetAssociatedHostIds(self):
    """User is primary_user of a Host and has an Event on that Host."""
    user = test_utils.CreateUser()
    other_user = test_utils.CreateUser()

    host = test_utils.CreateSantaHost(primary_user=user.nickname)
    host_not_primary1 = (
        test_utils.CreateSantaHost(primary_user=other_user.nickname))
    host_not_primary2 = (
        test_utils.CreateSantaHost(primary_user=other_user.nickname))

    blockable = test_utils.CreateSantaBlockable()
    parent_key = utils.ConcatenateKeys(
        user.key, host_not_primary1.key, blockable.key)
    test_utils.CreateSantaEvent(
        blockable, host_id=host_not_primary1.key.id(), parent=parent_key)

    associated_ids = santa.SantaHost.GetAssociatedHostIds(user)
    self.assertIn(host.key.id(), associated_ids)
    self.assertIn(host_not_primary1.key.id(), associated_ids)
    self.assertNotIn(host_not_primary2.key.id(), associated_ids)

  def testGetAssociatedUsers(self):
    host_id_1 = 'kiwi'
    host_id_2 = 'narwal'

    event_1 = utils.CopyEntity(
        self.santa_event, host_id=host_id_1, executing_user='user')
    event_2 = utils.CopyEntity(
        self.santa_event, host_id=host_id_2, executing_user='page')
    event_1.put()
    event_2.put()

    expected_users_1 = [event_1.executing_user]
    expected_users_2 = [event_2.executing_user]

    actual_users_1 = santa.SantaHost.GetAssociatedUsers(host_id_1)
    actual_users_2 = santa.SantaHost.GetAssociatedUsers(host_id_2)
    event_2.host_id = host_id_1
    event_2.put()
    users_combined = set(santa.SantaHost.GetAssociatedUsers(host_id_1))

    self.assertEqual(expected_users_1, actual_users_1)
    self.assertEqual(expected_users_2, actual_users_2)
    self.assertTrue(set(expected_users_1 + expected_users_2)
                    .issubset(users_combined))

  def testGetAssociatedHostIds_Overlap(self):
    """User is primary_user of a Host and has an Event on that Host."""
    user = test_utils.CreateUser()
    host = test_utils.CreateSantaHost(primary_user=user.nickname)
    blockable = test_utils.CreateSantaBlockable()
    test_utils.CreateSantaEvent(blockable, host_id=host.key.id())

    self.assertListEqual(
        [host.key.id()], santa.SantaHost.GetAssociatedHostIds(user))

  def testHostIsAssociatedWithUser_PrimaryUser(self):
    user = test_utils.CreateUser()
    host = test_utils.CreateSantaHost(primary_user=user.nickname)

    self.assertTrue(host.IsAssociatedWithUser(user))

  def testHostIsAssociatedWithUser_HasEvent(self):
    user = test_utils.CreateUser()
    other_user = test_utils.CreateUser()
    # Create a host not owned by `user`.
    host = test_utils.CreateSantaHost(primary_user=other_user.nickname)
    # Create an Event which was generated by `user`.
    parent_key = utils.ConcatenateKeys(
        user.key, host.key, self.santa_blockable.key)
    test_utils.CreateSantaEvent(
        self.santa_blockable, host_id=host.key.id(), parent=parent_key)

    self.assertTrue(host.IsAssociatedWithUser(user))

  def testHostIsAssociatedWithUser_NoEvent(self):
    user = test_utils.CreateUser()
    other_user = test_utils.CreateUser()
    # Create a host not owned by `user`.
    host = test_utils.CreateSantaHost(primary_user=other_user.nickname)

    self.assertFalse(host.IsAssociatedWithUser(user))


class SantaRuleTest(SantaModelTest):

  def testToDict_Package(self):
    blockable = test_utils.CreateSantaBlockable()
    bundle = test_utils.CreateSantaBundle(bundle_binaries=[blockable])
    rule = test_utils.CreateSantaRule(
        bundle.key, rule_type=constants.RULE_TYPE.PACKAGE)

    self.assertSameElements([blockable.key.id()], rule.to_dict()['binary_ids'])

  def testToDict_NotPackage(self):
    blockable = test_utils.CreateSantaBlockable()
    rule = test_utils.CreateSantaRule(
        blockable.key, rule_type=constants.RULE_TYPE.BINARY)

    self.assertNotIn('binary_ids', rule.to_dict())


if __name__ == '__main__':
  basetest.main()
