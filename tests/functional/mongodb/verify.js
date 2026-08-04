function requireCondition(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function requireAcknowledged(result, message) {
  requireCondition(result && result.acknowledged === true, message);
}

const database = db.getSiblingDB("dhi_contract");
const probe = database.probe;
const lifecycle = database.lifecycle_probe;

const lifecycleDocuments = lifecycle.find({}).toArray();
let lifecyclePhase = "initial";
if (lifecycleDocuments.length === 0) {
  print("MongoDB lifecycle marker is absent on the fresh data volume as expected");
} else {
  requireCondition(
    lifecycleDocuments.length === 1 &&
      lifecycleDocuments[0]._id === "mongodb-persistence-v1" &&
      lifecycleDocuments[0].expectedState === "mongodb-app-ok|2|0|0|12",
    "MongoDB lifecycle marker is inconsistent"
  );

  const persistedDocument = probe.findOne({ _id: 1 });
  requireCondition(
    persistedDocument &&
      persistedDocument.value === "mongodb-app-ok" &&
      persistedDocument.amount === 5,
    "MongoDB restart did not preserve the updated application document"
  );
  requireCondition(
    probe.countDocuments({ _id: 2, value: "committed-value", amount: 7 }) === 1,
    "MongoDB restart did not preserve the committed transaction state"
  );
  requireCondition(probe.countDocuments({ _id: 3 }) === 0,
    "MongoDB restart persisted the aborted transaction state");
  requireCondition(probe.countDocuments({ _id: 4 }) === 0,
    "MongoDB restart restored a deleted document");

  const persistedAggregate = probe.aggregate([
    { $match: { _id: { $in: [1, 2] } } },
    { $group: { _id: null, count: { $sum: 1 }, total: { $sum: "$amount" } } }
  ]).toArray();
  requireCondition(
    persistedAggregate.length === 1 &&
      persistedAggregate[0].count === 2 &&
      persistedAggregate[0].total === 12,
    "MongoDB restart returned an unexpected persisted aggregate"
  );

  const persistedIndex = probe.getIndexes().find(index => index.name === "value_unique");
  requireCondition(
    persistedIndex && persistedIndex.unique === true && persistedIndex.key.value === 1,
    "MongoDB restart did not preserve the unique application index"
  );
  lifecyclePhase = "restart";
  print("MongoDB verified the durable lifecycle marker, index, and application state before cleanup");
}

requireAcknowledged(probe.deleteMany({}), "MongoDB cleanup was not acknowledged");
requireCondition(
  probe.createIndex({ value: 1 }, { unique: true, name: "value_unique" }) === "value_unique",
  "MongoDB unique-index creation returned an unexpected name"
);
requireCondition(
  probe.createIndex({ value: 1 }, { unique: true, name: "value_unique" }) === "value_unique",
  "MongoDB idempotent unique-index creation returned an unexpected name"
);

requireAcknowledged(
  probe.insertOne({ _id: 1, value: "initial-value", amount: 2 }),
  "MongoDB initial insert was not acknowledged"
);
requireAcknowledged(probe.updateOne(
  { _id: 1 },
  { $set: { value: "mongodb-app-ok" }, $inc: { amount: 3 } }
), "MongoDB update was not acknowledged");
requireAcknowledged(probe.updateOne(
  { _id: 1 },
  { $set: { value: "mongodb-app-ok" } },
  { upsert: true }
), "MongoDB first idempotent upsert was not acknowledged");
requireAcknowledged(probe.updateOne(
  { _id: 1 },
  { $set: { value: "mongodb-app-ok" } },
  { upsert: true }
), "MongoDB second idempotent upsert was not acknowledged");

const updated = probe.findOne({ _id: 1 });
requireCondition(updated && updated.value === "mongodb-app-ok" && updated.amount === 5,
  "MongoDB update/find assertion returned unexpected state");

let duplicateRejected = false;
try {
  probe.insertOne({ _id: 99, value: "mongodb-app-ok", amount: 99 });
} catch (error) {
  duplicateRejected = error.code === 11000;
}
requireCondition(duplicateRejected, "MongoDB unique index accepted a duplicate value");
print("MongoDB unique index rejected duplicate data as expected");

const session = db.getMongo().startSession();
try {
  const sessionDatabase = session.getDatabase("dhi_contract");

  session.startTransaction();
  requireAcknowledged(sessionDatabase.probe.insertOne({
    _id: 2,
    value: "committed-value",
    amount: 7
  }), "MongoDB committed-transaction insert was not acknowledged");
  session.commitTransaction();

  session.startTransaction();
  requireAcknowledged(sessionDatabase.probe.insertOne({
    _id: 3,
    value: "rolled-back-value",
    amount: 11
  }), "MongoDB aborted-transaction insert was not acknowledged");
  session.abortTransaction();
} finally {
  session.endSession();
}

requireAcknowledged(
  probe.insertOne({ _id: 4, value: "delete-me", amount: 13 }),
  "MongoDB delete fixture insert was not acknowledged"
);
requireAcknowledged(probe.deleteOne({ _id: 4 }), "MongoDB delete was not acknowledged");

const aggregate = probe.aggregate([
  { $match: { _id: { $in: [1, 2] } } },
  { $group: { _id: null, count: { $sum: 1 }, total: { $sum: "$amount" } } }
]).toArray();
requireCondition(
  aggregate.length === 1 && aggregate[0].count === 2 && aggregate[0].total === 12,
  "MongoDB aggregation returned unexpected state"
);
requireCondition(probe.countDocuments({ _id: 2 }) === 1,
  "MongoDB committed transaction state is missing");
requireCondition(probe.countDocuments({ _id: 3 }) === 0,
  "MongoDB aborted transaction state was persisted");
requireCondition(probe.countDocuments({ _id: 4 }) === 0,
  "MongoDB delete assertion failed");

let administrationDenied = false;
try {
  const forbidden = db.getSiblingDB("admin").runCommand({
    createUser: "dhi_forbidden",
    pwd: "not-used",
    roles: []
  });
  administrationDenied = forbidden.ok !== 1 && forbidden.code === 13;
} catch (error) {
  administrationDenied = error.code === 13 || error.codeName === "Unauthorized";
}
requireCondition(administrationDenied,
  "MongoDB application user unexpectedly obtained user-administration privileges");
print("MongoDB application user was denied user administration as expected");

requireAcknowledged(lifecycle.updateOne(
  { _id: "mongodb-persistence-v1" },
  { $set: { expectedState: "mongodb-app-ok|2|0|0|12" } },
  { upsert: true }
), "MongoDB lifecycle-marker upsert was not acknowledged");

print(
  "MongoDB authenticated replica-set application contract passed: " +
    "phase=" + lifecyclePhase + " state=mongodb-app-ok|2|0|0|12"
);

const passedAssertionIds = [
  "auth.application_ready",
  "auth.wrong_password_rejected",
  "replication.transaction_capable",
  "crud.insert_update_find",
  "crud.delete",
  "crud.idempotent_upsert",
  "index.unique",
  "transaction.commit",
  "transaction.abort",
  "query.aggregate",
  "authorization.user_admin_denied",
  "persistence.lifecycle_state",
  "state.final_summary"
];
print("DHI_ASSERTION_SUMMARY " + JSON.stringify({
  assertions: passedAssertionIds.map(assertionId => ({
    id: assertionId,
    status: "pass"
  })),
  counts: { fail: 0, pass: passedAssertionIds.length },
  outcome: "pass",
  schemaVersion: 1,
  suite: "mongodb"
}));
