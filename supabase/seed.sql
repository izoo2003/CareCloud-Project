-- Demo patients. Obviously fake. Run once after 001_init.sql.
-- Phones are valid NANP (area code and exchange start with 2-9), 555-01xx style.

insert into patients (
  first_name,
  last_name,
  date_of_birth,
  sex,
  phone_number,
  email,
  address_line_1,
  address_line_2,
  city,
  state,
  zip_code,
  preferred_language
) values
(
  'Jane',
  'Doe',
  '1988-03-14',
  'Female',
  '5125550101',
  'jane.doe@example.com',
  '42 Elm Street',
  null,
  'Austin',
  'TX',
  '78701',
  'English'
),
(
  'John',
  'Public',
  '1975-07-04',
  'Male',
  '5125550199',
  'john.public@example.com',
  '100 Main Street',
  'Apt 2',
  'Springfield',
  'IL',
  '62701',
  'English'
);
